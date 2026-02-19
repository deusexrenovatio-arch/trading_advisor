from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone

import pandas as pd
import requests
from dash.dash_table.Format import Format, Scheme, Trim
from flask import jsonify

from moex_carry.config import AppSettings
from moex_carry.domain.decision_engine import (
    build_signal_gate_results,
    derive_signal_lifecycle_state,
)
from moex_carry.signals_delivery import parse_iso_utc


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _append_jsonl(path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _latest_by_decision_id(records: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    latest: dict[str, dict[str, object]] = {}
    for record in records:
        decision_id = record.get("decision_id")
        if isinstance(decision_id, str) and decision_id:
            latest[decision_id] = record
    return latest


def _table_columns(df):
    return [{"name": col, "id": col} for col in df.columns]


def _decision_columns():
    return [
        {"name": "Time", "id": "created_at"},
        {"name": "Decision", "id": "decision_id"},
        {"name": "Strategy", "id": "strategy_type"},
        {"name": "Instrument", "id": "primary_instrument"},
        {"name": "Action", "id": "action"},
        {"name": "Risk", "id": "risk_state"},
        {"name": "News", "id": "news_severity"},
        {
            "name": "Cost",
            "id": "cost_round_trip",
            "type": "numeric",
            "format": Format(precision=2, scheme=Scheme.fixed, trim=Trim.yes),
        },
        {
            "name": "Max DD",
            "id": "max_drawdown",
            "type": "numeric",
            "format": Format(precision=4, scheme=Scheme.fixed, trim=Trim.yes),
        },
    ]


def _prepare_decisions(decisions: pd.DataFrame) -> pd.DataFrame:
    if decisions.empty:
        return decisions
    decisions = decisions.copy()
    if "cost_summary.round_trip_cost" in decisions.columns:
        decisions["cost_round_trip"] = decisions["cost_summary.round_trip_cost"]
    if "backtest_metrics.max_drawdown" in decisions.columns:
        decisions["max_drawdown"] = decisions["backtest_metrics.max_drawdown"]
    display_columns = [
        "created_at",
        "decision_id",
        "strategy_type",
        "primary_instrument",
        "action",
        "risk_state",
        "news_severity",
        "cost_round_trip",
        "max_drawdown",
    ]
    for col in display_columns:
        if col not in decisions.columns:
            decisions[col] = None
    decisions["cost_round_trip"] = pd.to_numeric(decisions["cost_round_trip"], errors="coerce")
    decisions["max_drawdown"] = pd.to_numeric(decisions["max_drawdown"], errors="coerce")
    return decisions[display_columns].sort_values("created_at", ascending=False)


def _sanitize_value(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {key: _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def _contains_nan(value) -> bool:
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, dict):
        return any(_contains_nan(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_nan(item) for item in value)
    return False


def _parse_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n"}:
            return False
    return None


def _coerce_bool(value: object, *, default: bool) -> bool:
    parsed = _parse_bool(value)
    if parsed is None:
        return bool(default)
    return parsed


def _default_require_score_gate_for_signals(settings: AppSettings) -> bool:
    return bool(getattr(settings.ui, "require_score_gate_by_default", True))


def _default_require_score_gate_for_top_pairs(settings: AppSettings) -> bool:
    # Top-pairs should reflect historical ranking by default.
    return bool(settings.ui.require_score_gate_top_pairs_by_default)


def _resolve_require_score_gate(value: object, *, default: bool) -> bool:
    return _coerce_bool(value, default=default)


def _apply_score_gate_filter(df: pd.DataFrame, *, require_score_gate: bool) -> pd.DataFrame:
    if not require_score_gate or df.empty or "score_gate_pass" not in df.columns:
        return df
    gate_mask = df["score_gate_pass"].map(lambda value: _coerce_bool(value, default=False))
    return df.loc[gate_mask].copy()


def _record_score_gate_pass(record: dict[str, object]) -> bool:
    direct = _parse_bool(record.get("score_gate_pass"))
    if direct is not None:
        return bool(direct)
    metrics = record.get("signal_metrics")
    if isinstance(metrics, dict):
        nested = _parse_bool(metrics.get("score_gate_pass"))
        if nested is not None:
            return bool(nested)
    return False


def _parse_int(value: object, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_float(value: object, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bad_request(message: str, *, details: object | None = None):
    payload = {"error": "invalid_request", "message": message}
    if details is not None:
        payload["details"] = details
    return jsonify(payload), 400


_TRANSPORT_ERROR_TYPES = (
    requests.exceptions.SSLError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def _iter_exception_chain(exc: BaseException):
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None:
        key = id(current)
        if key in visited:
            break
        visited.add(key)
        yield current
        current = current.__cause__ if current.__cause__ is not None else current.__context__


def _is_iss_transport_error(exc: BaseException) -> bool:
    for item in _iter_exception_chain(exc):
        if isinstance(item, _TRANSPORT_ERROR_TYPES):
            return True
        if isinstance(item, requests.exceptions.RequestException):
            response = getattr(item, "response", None)
            if response is None:
                return True
    return False


def _build_pretrade_fail_open_result(
    *,
    stock: str,
    future: str,
    direction: str,
    spot_target: float,
    future_target: float,
    spread_target: float,
    eps: float,
    stock_eps: float,
    future_eps: float,
    spread_eps: float,
    future_scale: float,
    qty_fut: float,
    participation_rate: float,
    min_hits: int,
    error_text: str,
) -> dict[str, object]:
    stock_buy_max = float(spot_target) * (1.0 + float(stock_eps))
    stock_sell_min = float(spot_target) * (1.0 - float(stock_eps))
    fut_buy_max = float(future_target) * (1.0 + float(future_eps))
    fut_sell_min = float(future_target) * (1.0 - float(future_eps))
    spread_base = max(abs(float(spread_target)), 1.0)
    spread_band = spread_base * float(spread_eps)
    spread_min = float(spread_target) - spread_band
    spread_max = float(spread_target) + spread_band

    qty_stock = max(float(future_scale), 1.0) * float(qty_fut)
    min_session_volume_stock = qty_stock / float(participation_rate)
    min_session_volume_fut = float(qty_fut) / float(participation_rate)

    return {
        "status": "PLACE",
        "ready_to_place": True,
        "manual_confirm_required": True,
        "degraded": True,
        "gate_policy": {
            "mode": "iss_manual_drive_transport_fail_open",
            "blocking_gates": [],
            "advisory_gates": [
                "stock_quote_pass",
                "fut_quote_pass",
                "stock_price_pass",
                "fut_price_pass",
                "spread_pass",
                "sync_pass",
                "stock_volume_pass",
                "fut_volume_pass",
            ],
        },
        "pair": {
            "stock": stock,
            "future": future,
            "direction": direction,
        },
        "targets": {
            "spot_target": float(spot_target),
            "future_target_per_share": float(future_target),
            "spread_target": float(spread_target),
        },
        "order_price_bands": {
            "stock_buy_max": stock_buy_max,
            "stock_sell_min": stock_sell_min,
            "future_buy_max_per_share": fut_buy_max,
            "future_sell_min_per_share": fut_sell_min,
            "future_buy_max_contract": fut_buy_max * float(future_scale),
            "future_sell_min_contract": fut_sell_min * float(future_scale),
            "spread_min": spread_min,
            "spread_max": spread_max,
        },
        "volume_requirements": {
            "qty_fut_contracts": float(qty_fut),
            "qty_stock_shares": qty_stock,
            "participation_rate": float(participation_rate),
            "min_session_volume_stock": min_session_volume_stock,
            "min_session_volume_fut_contracts": min_session_volume_fut,
        },
        "gates": {},
        "hits": {
            "required": int(max(min_hits, 1)),
            "snapshots": 0,
        },
        "reasons": [],
        "advisory_reasons": ["iss_transport_error"],
        "diagnostics": {
            "transport_error": error_text,
            "eps": float(eps),
            "stock_eps": float(stock_eps),
            "future_eps": float(future_eps),
            "spread_eps": float(spread_eps),
        },
    }


def _df_to_records(df: pd.DataFrame) -> list[dict[str, object]]:
    if df.empty:
        return []
    cleaned = df.astype(object).where(pd.notna(df), None)
    records = cleaned.to_dict("records")
    return [_sanitize_value(record) for record in records]


def _stringify_datetime_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    result = df.copy()
    for column in result.columns:
        if "date" in str(column).lower():
            converted = pd.to_datetime(result[column], errors="coerce")
            if converted.notna().any():
                result[column] = converted.dt.strftime("%Y-%m-%d")
                continue
        if "ts" in str(column).lower() or "time" in str(column).lower():
            converted = pd.to_datetime(result[column], errors="coerce")
            if converted.notna().any():
                result[column] = converted.dt.strftime("%Y-%m-%d %H:%M:%S")
    return result


SIGNAL_METRIC_CONTRACT_KEYS: tuple[str, ...] = (
    "entry_price_tolerance_pct",
    "entry_stock_min",
    "entry_stock_max",
    "entry_future_min_per_share",
    "entry_future_max_per_share",
    "entry_spread_min",
    "entry_spread_max",
    "entry_spread_pct_min",
    "entry_spread_pct_max",
    "tp_net",
    "sl_net",
    "tp_spread_pct_level",
    "sl_spread_pct_level",
    "tp_spread_level",
    "sl_spread_level",
    "tp_stock_level_if_fut_const",
    "sl_stock_level_if_fut_const",
    "tp_future_level_if_stock_const",
    "sl_future_level_if_stock_const",
    "forecast_tp_probability",
    "forecast_sl_probability",
    "forecast_tp_first_probability",
    "forecast_sl_first_probability",
    "forecast_no_exit_first_probability",
    "forecast_n_effective",
    "forecast_confidence_tier",
    "forecast_exit_days",
    "forecast_exit_date",
    "forecast_model",
    "forecast_probability_source",
    "forward_n_effective",
    "forward_confidence_tier",
    "orderbook_pass",
    "orderbook_stock_min_depth",
    "orderbook_fut_min_depth",
    "orderbook_stock_quote_age_sec",
    "orderbook_fut_quote_age_sec",
    "orderbook_stock_imbalance",
    "orderbook_fut_imbalance",
    "orderbook_stock_quote_available",
    "orderbook_fut_quote_available",
    "orderbook_stock_depth_available",
    "orderbook_fut_depth_available",
    "orderbook_data_warnings",
    "floor_rate_annual",
    "rtc_pct",
    "spread_pct",
    "score_model",
    "score_target_annual",
    "score_floor",
    "score_floor_excess_annual",
    "score_alpha",
    "score_edge_raw_annual",
    "score_exec_probability",
    "score_earn_probability",
    "score_gate_exec_threshold",
    "score_gate_earn_threshold",
    "score_gate_pass",
    "total_score",
    "avg_trade_return_annual_recent",
    "avg_trade_return_annual_operational_recent",
    "share_target_pass",
    "unfilled_entry_rate",
    "unfilled_exit_rate",
    "forced_exit_rate",
)


def _normalize_signal_metrics(metrics: object) -> dict[str, object]:
    normalized: dict[str, object]
    if isinstance(metrics, dict):
        normalized = {str(key): _sanitize_value(value) for key, value in metrics.items()}
    else:
        normalized = {}
    for key in SIGNAL_METRIC_CONTRACT_KEYS:
        normalized.setdefault(key, None)
    return normalized


def _merge_signal_metrics(record: dict[str, object]) -> dict[str, object]:
    metrics = _normalize_signal_metrics(record.get("signal_metrics"))
    merged = dict(record)
    merged["signal_metrics"] = metrics
    for key, value in metrics.items():
        if key not in merged:
            merged[key] = _sanitize_value(value)
    return merged


def _build_execution_quality(record: dict[str, object]) -> dict[str, object]:
    metrics = _normalize_signal_metrics(record.get("signal_metrics"))

    def _pick(*keys: str):
        for key in keys:
            if key in record and record.get(key) is not None:
                return _sanitize_value(record.get(key))
            if key in metrics and metrics.get(key) is not None:
                return _sanitize_value(metrics.get(key))
        return None

    return {
        "unfilled_entry_rate": _pick("unfilled_entry_rate"),
        "unfilled_exit_rate": _pick("unfilled_exit_rate"),
        "forced_exit_rate": _pick("forced_exit_rate"),
        "entry_wait_minutes_mean": _pick("avg_entry_wait_min_closed"),
        "exit_wait_minutes_mean": _pick("avg_exit_wait_min_closed"),
        "trades_closed_sample": _pick("trades_closed"),
        "entry_signals_sample": _pick("entry_signals"),
        "exit_signals_sample": _pick("exit_signals"),
    }


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _normalize_execution_leg(value: object) -> str:
    if value is None:
        return "other"
    raw = str(value).strip().lower()
    if not raw:
        return "other"
    if raw in {"stock", "spot", "cash", "equity", "Р В°Р С”РЎвЂ Р С‘РЎРЏ"}:
        return "stock"
    if raw in {"future", "futures", "fut", "РЎвЂћРЎРЉРЎР‹РЎвЂЎР ВµРЎР‚РЎРѓ", "РЎвЂћРЎРЉРЎР‹РЎвЂЎР ВµРЎР‚РЎРѓРЎвЂ№"}:
        return "future"
    return "other"


def _normalize_execution_action(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"exit", "close"}:
        return "exit"
    if raw in {"ack", "acknowledged"}:
        return "ack"
    if raw in {"enter", "open", "hold_open", "hold"}:
        # hold_open in execution logs is treated as opening/maintaining leg exposure.
        return "enter"
    return raw or "enter"


def _coerce_signal_action_request(
    value: object, *, legacy_mode: bool = False
) -> tuple[str, str] | None:
    raw = str(value or "").strip().lower()
    if raw in {"ack", "acknowledged"}:
        return "ack", "ack"
    if raw in {"enter", "open"}:
        return "enter", "enter"
    if raw in {"exit", "close"}:
        return "exit", "exit"
    if raw in {"hold", "hold_open"}:
        if legacy_mode:
            # Keep v1 storage semantics: hold-like actions are persisted as enter.
            return "enter", "enter"
        return "hold", "hold_open"
    return None


def _normalize_signal_action_source(value: object, *, default: str) -> str:
    source = str(value or default).strip().lower()
    allowed = {"ui", "telegram", "system"}
    if default == "v1_adapter":
        allowed.add("v1_adapter")
    if source in allowed:
        return source
    return default


def _normalize_order_id(value: object) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    return raw or None


def _stable_id(prefix: str, *parts: object, length: int = 16) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[: max(length, 8)]
    return f"{prefix}-{digest}"


def _build_pair_entity_ref(stock: object, future: object) -> dict[str, object]:
    stock_value = str(stock or "").strip()
    future_value = str(future or "").strip()
    entity_id = f"{stock_value}:{future_value}" if stock_value or future_value else ""
    return {
        "entity_type": "pair",
        "entity_id": entity_id,
        "ticker": stock_value or None,
    }


def _build_signal_id_from_row(row: dict[str, object]) -> str:
    fingerprint = str(row.get("signal_fingerprint") or "").strip()
    if fingerprint:
        return _stable_id(
            "sig",
            fingerprint,
            row.get("stock"),
            row.get("future"),
            row.get("signal_action"),
        )
    return _stable_id(
        "sig",
        row.get("run_id"),
        row.get("timestamp"),
        row.get("stock"),
        row.get("future"),
        row.get("signal_action"),
    )


def _derive_lifecycle_state(row: dict[str, object]) -> str:
    return derive_signal_lifecycle_state(
        row.get("signal_action"),
        position_open=bool(row.get("position_open")),
    )


def _derive_effective_signal_action(row: dict[str, object]) -> str:
    action = str(row.get("signal_action") or "").strip().lower()
    if action != "enter":
        return action or "hold"
    pretrade_status = str(row.get("pretrade_status") or "").strip().lower()
    if pretrade_status in {"hold", "block"}:
        return "hold_pretrade"
    if pretrade_status in {"check", "pending"}:
        return "check_pretrade"
    return "enter"


def _build_gate_results_from_row(row: dict[str, object], signal_id: str) -> list[dict[str, object]]:
    metrics = row.get("signal_metrics")
    if isinstance(metrics, dict) and row.get("score_gate_pass") is not None:
        metrics = {**metrics, "score_gate_pass": row.get("score_gate_pass")}
    return build_signal_gate_results(
        signal_id=signal_id,
        action=row.get("signal_action"),
        signal_metrics=metrics,
        pretrade_status=row.get("pretrade_status"),
        pretrade_reasons=row.get("pretrade_reasons"),
        stable_id=_stable_id,
    )


_ACTIONABILITY_GATE_PRIORITIES: tuple[tuple[str, int], ...] = (
    ("risk_profile", 1),
    ("news_geopolitics", 2),
    ("liquidity", 3),
    ("execution_feasibility", 4),
    ("source_freshness", 5),
    ("portfolio_limits", 6),
    ("venue_constraints", 7),
)


def _normalize_gate_status(value: object, *, default: str = "unavailable") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"pass", "reduce", "review", "block", "unavailable"}:
        return normalized
    return default


def _coerce_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                result.append(text)
        return result
    if isinstance(value, str):
        text = value.strip()
        if text:
            return [text]
    return []


def _contains_reason_token(reasons: list[str], *tokens: str) -> bool:
    lowered = [item.lower() for item in reasons]
    for token in tokens:
        token_value = token.lower()
        if any(token_value in reason for reason in lowered):
            return True
    return False


_EVIDENCE_SOURCE_KINDS = {
    "technical",
    "fundamental",
    "news",
    "quant_model",
    "liquidity",
    "risk",
    "manual",
    "other",
}
_EVIDENCE_STANCES = {"support", "oppose", "neutral"}
_EVIDENCE_SEVERITIES = {"low", "medium", "high", "critical"}


def _normalize_evidence_source_kind(value: object, *, default: str = "other") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _EVIDENCE_SOURCE_KINDS:
        return normalized
    return default


def _normalize_evidence_stance(value: object, *, default: str = "neutral") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _EVIDENCE_STANCES:
        return normalized
    return default


def _normalize_evidence_severity(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in _EVIDENCE_SEVERITIES:
        return normalized
    return None


def _derive_evidence_freshness_sec(observed_at: object, snapshot_as_of: object) -> int | None:
    observed_dt = parse_iso_utc(observed_at)
    snapshot_dt = parse_iso_utc(snapshot_as_of)
    if observed_dt is None or snapshot_dt is None:
        return None
    delta_sec = int((snapshot_dt - observed_dt).total_seconds())
    if delta_sec < 0:
        return 0
    return delta_sec


def _normalize_evidence_item(
    item: dict[str, object],
    *,
    snapshot_as_of: object,
    fallback_source_key_parts: tuple[object, ...] = (),
) -> dict[str, object]:
    normalized_item = dict(item)
    normalized_item["source_kind"] = _normalize_evidence_source_kind(
        normalized_item.get("source_kind"),
        default="other",
    )
    normalized_item["stance"] = _normalize_evidence_stance(
        normalized_item.get("stance"),
        default="neutral",
    )
    normalized_item["reason_codes"] = _coerce_string_list(normalized_item.get("reason_codes"))

    source_key = str(normalized_item.get("source_key") or "").strip()
    if not source_key:
        source_key = _stable_id(
            "evidence",
            normalized_item.get("source_kind"),
            normalized_item.get("observed_at"),
            *fallback_source_key_parts,
            normalized_item.get("reason_codes"),
        )
    normalized_item["source_key"] = source_key

    severity = _normalize_evidence_severity(normalized_item.get("severity"))
    normalized_item["severity"] = severity

    confidence = _to_float(normalized_item.get("confidence"))
    if confidence is not None:
        normalized_item["confidence"] = min(max(float(confidence), 0.0), 1.0)

    freshness_sec = normalized_item.get("freshness_sec")
    freshness_value = None
    if freshness_sec is not None:
        parsed = _to_float(freshness_sec)
        if parsed is not None:
            freshness_value = max(int(parsed), 0)
    if freshness_value is None:
        freshness_value = _derive_evidence_freshness_sec(
            normalized_item.get("observed_at"),
            snapshot_as_of,
        )
    if freshness_value is not None:
        normalized_item["freshness_sec"] = freshness_value

    return normalized_item

