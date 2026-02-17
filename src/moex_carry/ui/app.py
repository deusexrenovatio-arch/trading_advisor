from __future__ import annotations

import json
import hashlib
import logging
import math
from pathlib import Path
import threading
import uuid
from datetime import datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dash import Dash, Input, Output, State, dash_table, dcc, html
from dash.dash_table.Format import Format, Scheme, Trim
from flask import Flask, jsonify, request
from pydantic import ValidationError

from moex_carry.config import AppSettings, resolve_paths
from moex_carry.contracts.strategy_test import BacktestRequest, ForwardTestRequest, HpoRequest
from moex_carry.backtest_v2.runtime import run_backtest_v2_cached, serialize_backtest_report
from moex_carry.data.moex_iss import MoexIssClient
from moex_carry.decision_log import load_jsonl
from moex_carry.domain.decision_engine import (
    build_decision_action_entries,
    build_signal_gate_results,
    derive_signal_lifecycle_state,
    parse_decision_action_request,
)
from moex_carry.domain.execution_policy import (
    evaluate_fail_closed_entry,
    select_auto_unwind_candidates,
)
from moex_carry.domain.pretrade_service import (
    PretradeRuntimeParams,
    enrich_pretrade_result,
    normalize_pretrade_direction,
)
from moex_carry.forward.runtime import load_forward_status, start_forward_run
from moex_carry.hpo.runtime import load_hpo_status, start_hpo_run
from moex_carry.minute_ingest.runner import run_incremental_minute_ingest
from moex_carry.observability.runtime_metrics import ApiObservability
from moex_carry.parameter_specs import get_parameter_specs
from moex_carry.pipeline import build_spread_series, run_signal_cycle
from moex_carry.pretrade.delay_gate import run_delay_gate
from moex_carry.signals_ack import build_signal_fingerprint, parse_ack_note
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_decision_view_projection,
    load_active_signals,
    load_latest_signal_run,
    load_open_executions,
    load_signal_executions,
    load_signal_history,
    store_signal_history,
    store_signal_execution,
    store_signal_run,
)
from moex_carry.ui.data import (
    load_backtest_summary,
    load_decision_log,
    load_decision_view,
    load_signals,
    load_top_pairs,
)
from moex_carry.ui.unified_runtime import (
    UnifiedMarketSnapshot,
    build_unified_market_snapshot,
    build_unified_spread_series,
    get_last_refresh_telemetry,
    list_unified_ingest_pairs,
    persist_snapshot_to_csv,
)


BASE_TABLE_STYLE = {
    "style_table": {"overflowX": "auto", "border": "1px solid #e5e7eb"},
    "style_header": {
        "backgroundColor": "#f9fafb",
        "fontWeight": "600",
        "border": "1px solid #e5e7eb",
    },
    "style_cell": {
        "fontFamily": "Arial, sans-serif",
        "fontSize": "12px",
        "padding": "6px",
        "whiteSpace": "nowrap",
        "textOverflow": "ellipsis",
        "maxWidth": "180px",
        "border": "1px solid #f0f0f0",
    },
}


_CACHE_VERSION = "v5"
_V1_DEPRECATION_SUNSET_HTTP = "Wed, 01 Jul 2026 00:00:00 GMT"
_V1_DEPRECATION_SUNSET_DATE = "2026-07-01"


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
    spread_band = float(spot_target) * float(spread_eps)
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
    "forecast_exit_days",
    "forecast_exit_date",
    "forecast_model",
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
    if raw in {"stock", "spot", "cash", "equity", "акция"}:
        return "stock"
    if raw in {"future", "futures", "fut", "фьючерс", "фьючерсы"}:
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


def _extract_response_payload(result) -> tuple[object | None, int]:
    if isinstance(result, tuple):
        payload, status_code = result[0], int(result[1])
    else:
        payload, status_code = result, 200
    if hasattr(payload, "get_json"):
        data = payload.get_json(silent=True)
        return data, status_code
    return payload, status_code


def _extract_idempotency_key(note: object) -> str | None:
    if not isinstance(note, str) or not note.strip():
        return None
    try:
        payload = json.loads(note)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("idempotency_key")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _deprecated_v1_successor_path(request_path: str) -> str | None:
    if request_path == "/api/top-pairs":
        return "/api/v2/top-pairs"
    if request_path == "/api/decision-view":
        return "/api/v2/decision-view"
    if request_path == "/api/pretrade/check":
        return "/api/v2/pretrade/check"
    if request_path == "/api/signals/active":
        return "/api/v2/signals/active"
    if request_path == "/api/signals/history":
        return "/api/v2/signals/history"
    if request_path == "/api/signals/executions":
        return "/api/v2/signals/executions"
    if request_path == "/api/signals/execute":
        return "/api/v2/signals/{signal_id}/actions"
    if request_path.startswith("/api/decisions/") and request_path.endswith("/action"):
        decision_id = request_path.removeprefix("/api/decisions/").removesuffix("/action")
        decision_id = decision_id.strip("/")
        if decision_id:
            return f"/api/v2/decisions/{decision_id}/actions"
    return None


def _signal_used_by_from_ack(note_payload: dict[str, object]) -> str | None:
    username = note_payload.get("telegram_username")
    if isinstance(username, str) and username.strip():
        return username.strip()
    user_id = note_payload.get("telegram_user_id")
    if isinstance(user_id, int):
        return str(user_id)
    return None


def _decrement_leg_bucket(open_legs: dict[str, int], preferred: str) -> None:
    if preferred in open_legs and int(open_legs.get(preferred, 0)) > 0:
        open_legs[preferred] = int(open_legs.get(preferred, 0)) - 1
        return
    if int(open_legs.get("other", 0)) > 0:
        open_legs["other"] = int(open_legs.get("other", 0)) - 1
        return
    if int(open_legs.get("stock", 0)) >= int(open_legs.get("future", 0)):
        if int(open_legs.get("stock", 0)) > 0:
            open_legs["stock"] = int(open_legs.get("stock", 0)) - 1
            return
        if int(open_legs.get("future", 0)) > 0:
            open_legs["future"] = int(open_legs.get("future", 0)) - 1
            return
    if int(open_legs.get("future", 0)) > 0:
        open_legs["future"] = int(open_legs.get("future", 0)) - 1
        return
    if int(open_legs.get("stock", 0)) > 0:
        open_legs["stock"] = int(open_legs.get("stock", 0)) - 1


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_daily_time(raw: str | None) -> dt_time | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            return dt_time(parsed.hour, parsed.minute, parsed.second)
        except ValueError:
            continue
    return None


def _resolve_tz(raw: str | None, fallback: str) -> timezone:
    name = raw or fallback or "UTC"
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def _next_daily_run(now_utc: datetime, target: dt_time, tzinfo: timezone) -> datetime:
    local_now = now_utc.astimezone(tzinfo)
    target_local = local_now.replace(
        hour=target.hour,
        minute=target.minute,
        second=target.second,
        microsecond=0,
    )
    if target_local <= local_now:
        target_local = target_local + timedelta(days=1)
    return target_local.astimezone(timezone.utc)


def _parse_date_bound(raw: str, bound: str) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        if "T" not in raw and " " not in raw:
            day = datetime.fromisoformat(raw).date()
            if bound == "end":
                return datetime.combine(day, datetime.max.time())
            return datetime.combine(day, datetime.min.time())
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return _normalize_datetime(parsed)


def _future_scale_from_raw(path, secid: str) -> float:
    if not path.exists():
        return 1.0
    try:
        futures_df = pd.read_csv(path)
    except Exception:
        return 1.0
    if futures_df.empty or "SECID" not in futures_df.columns:
        return 1.0
    rows = futures_df[futures_df["SECID"].astype(str) == str(secid)]
    if rows.empty:
        return 1.0
    row = rows.iloc[0]
    lot = pd.to_numeric(row.get("LOTVOLUME"), errors="coerce")
    multiplier = pd.to_numeric(row.get("MULTIPLIER"), errors="coerce")
    lot_value = float(lot) if pd.notna(lot) and float(lot) > 0 else 1.0
    mult_value = float(multiplier) if pd.notna(multiplier) and float(multiplier) > 0 else 1.0
    return lot_value * mult_value


def _read_cache(path, ttl_minutes: int) -> list[dict[str, object]] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    generated_at = payload.get("generated_at")
    if not generated_at:
        return None
    try:
        generated_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if datetime.now(timezone.utc) - generated_dt > timedelta(minutes=ttl_minutes):
        return None
    series = payload.get("series")
    if not isinstance(series, list):
        return None
    if series and isinstance(series[0], dict):
        if not {
            "zscore",
            "z_entry",
            "z_exit",
            "entry_flag",
            "exit_flag",
            "entry_cycle",
            "exit_cycle",
            "cycle_return_pct",
        }.issubset(series[0].keys()):
            return None
    if _contains_nan(series):
        return None
    return series


def _write_cache(path, series: list[dict[str, object]]) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "series": series,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def _apply_query_filters(df: pd.DataFrame, args) -> pd.DataFrame:
    if df.empty:
        return df
    filters = {
        "strategy_type": args.get("strategy_type"),
        "primary_instrument": args.get("primary_instrument"),
        "risk_state": args.get("risk_state"),
        "news_severity": args.get("news_severity"),
    }
    for column, value in filters.items():
        if value:
            df = df[df[column] == value]
    created_from = args.get("created_from")
    created_to = args.get("created_to")
    if created_from or created_to:
        df = df.copy()
        df["created_at_parsed"] = pd.to_datetime(df.get("created_at"), errors="coerce")
        if created_from:
            df = df[df["created_at_parsed"] >= pd.to_datetime(created_from, errors="coerce")]
        if created_to:
            df = df[df["created_at_parsed"] <= pd.to_datetime(created_to, errors="coerce")]
        df = df.drop(columns=["created_at_parsed"])
    return df


DECISION_STYLE = [
    {"if": {"column_id": "decision_id"}, "fontFamily": "monospace"},
    {"if": {"column_id": "action", "filter_query": "{action} = 'approve'"}, "color": "#116329"},
    {"if": {"column_id": "action", "filter_query": "{action} = 'reject'"}, "color": "#9b1c1c"},
    {"if": {"column_id": "risk_state", "filter_query": "{risk_state} = 'green'"}, "color": "#116329"},
    {"if": {"column_id": "risk_state", "filter_query": "{risk_state} = 'yellow'"}, "color": "#a16207"},
    {"if": {"column_id": "risk_state", "filter_query": "{risk_state} = 'red'"}, "color": "#9b1c1c"},
    {"if": {"column_id": "news_severity", "filter_query": "{news_severity} = 'high'"}, "color": "#9b1c1c"},
    {"if": {"column_id": "news_severity", "filter_query": "{news_severity} = 'critical'"}, "color": "#7f1d1d"},
]


def create_app(settings: AppSettings) -> Dash:
    paths = resolve_paths(settings)
    server = Flask(__name__)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    decisions_dir = paths.data_dir / "decisions"
    actions_path = decisions_dir / "decision_actions.jsonl"
    executions_path = decisions_dir / "execution_requests.jsonl"
    logger = logging.getLogger(__name__)
    observability = ApiObservability(latency_window_size=1000)

    def _observe_request(endpoint_key: str, started_at: datetime, result):
        _, status_code = _extract_response_payload(result)
        duration_ms = max((datetime.now(timezone.utc) - started_at).total_seconds() * 1000.0, 0.0)
        observability.record_request(endpoint_key, status_code=status_code, duration_ms=duration_ms)
        return result

    def _mark_signal_action_events(result) -> None:
        payload, status_code = _extract_response_payload(result)
        if status_code == 409 and isinstance(payload, dict):
            if str(payload.get("error") or "").strip().lower() == "fail_closed_execution":
                observability.mark_event("execution_rejected_fail_closed")

    def _mark_pretrade_events(result) -> None:
        payload, status_code = _extract_response_payload(result)
        if status_code >= 500:
            observability.mark_event("pretrade_error")
            return
        if status_code >= 400 or not isinstance(payload, dict):
            return
        pretrade_status = str(payload.get("pretrade_status") or payload.get("status") or "").strip().lower()
        ready_to_place = _parse_bool(payload.get("ready_to_place"))
        if pretrade_status in {"block", "check", "pending"} or ready_to_place is False:
            observability.mark_event("pretrade_failure")
        degraded = _parse_bool(payload.get("degraded"))
        if degraded is True:
            observability.mark_event("pretrade_degraded")

    def _mark_auto_unwind_events(result) -> None:
        payload, status_code = _extract_response_payload(result)
        if status_code >= 500:
            observability.mark_event("auto_unwind_error")
            return
        if status_code >= 400 or not isinstance(payload, dict):
            return
        triggered_count = _parse_int(payload.get("triggered_count"), 0)
        blocked_count = _parse_int(payload.get("blocked_count"), 0)
        error_count = _parse_int(payload.get("error_count"), 0)
        if triggered_count > 0:
            observability.mark_event("auto_unwind_triggered", count=triggered_count)
        if blocked_count > 0:
            observability.mark_event("auto_unwind_blocked", count=blocked_count)
        if error_count > 0:
            observability.mark_event("auto_unwind_error", count=error_count)

    refresh_enabled = bool(settings.ui.signal_refresh_enabled)
    refresh_interval = int(settings.ui.signal_refresh_interval_sec or 0)
    refresh_daily_time = _parse_daily_time(settings.ui.signal_refresh_daily_time)
    refresh_tz = _resolve_tz(settings.ui.signal_refresh_timezone, settings.environment.timezone)
    refresh_mode = "daily" if refresh_daily_time else "interval"
    incremental_enabled = bool(getattr(settings.ui, "incremental_replay_enabled", True))
    refresh_durations_ms: list[float] = []
    refresh_state = {
        "enabled": refresh_enabled,
        "interval_sec": refresh_interval,
        "mode": refresh_mode,
        "daily_time": settings.ui.signal_refresh_daily_time,
        "timezone": settings.ui.signal_refresh_timezone or settings.environment.timezone,
        "incremental_enabled": incremental_enabled,
        "data_watermark_before": None,
        "data_watermark_after": None,
        "pairs_total": 0,
        "pairs_recomputed": 0,
        "pairs_reused": 0,
        "pairs_skipped": 0,
        "skip_reason": None,
        "ingest_lag_sec": None,
        "cache_hit_ratio": 0.0,
        "fallback_full_replay_count": 0,
        "refresh_duration_ms_p50": 0.0,
        "refresh_duration_ms_p95": 0.0,
        "staleness_age_sec": None,
        "status": "disabled",
        "last_started_at": None,
        "last_success_at": None,
        "last_error": None,
        "next_run_at": None,
    }
    refresh_lock = threading.Lock()
    refresh_stop = threading.Event()

    def _unified_ttl_sec() -> int:
        return max(int(getattr(settings.ui, "unified_snapshot_ttl_sec", 120) or 0), 1)

    def _resolved_unified_max_pairs(fallback: int | None = None) -> int | None:
        configured = settings.ui.signal_refresh_max_pairs
        if configured is not None and int(configured) > 0:
            return int(configured)
        strategy_max = int(settings.strategy.max_pairs or 0)
        if strategy_max > 0:
            return strategy_max
        if fallback is not None and int(fallback) > 0:
            return int(fallback)
        return None

    def _resolve_incremental_checkpoint_root() -> Path:
        configured = Path(str(getattr(settings.ui, "incremental_checkpoint_dir", "./data/state/incremental_replay")))
        if configured.is_absolute():
            return configured
        text = str(configured).replace("\\", "/")
        if text.startswith("./data/"):
            return paths.data_dir.parent / text[2:]
        if text.startswith("data/"):
            return paths.data_dir.parent / text
        return paths.data_dir / configured

    def _percentile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        data = sorted(float(item) for item in values)
        if len(data) == 1:
            return data[0]
        rank = (len(data) - 1) * max(0.0, min(float(q), 100.0)) / 100.0
        lower = int(rank)
        upper = min(lower + 1, len(data) - 1)
        if lower == upper:
            return data[lower]
        weight = rank - lower
        return data[lower] * (1.0 - weight) + data[upper] * weight

    def _unified_snapshot(
        max_pairs: int | None,
        *,
        force: bool = False,
        ingest_cycle=None,
    ) -> UnifiedMarketSnapshot:
        return build_unified_market_snapshot(
            settings,
            paths.data_dir,
            force=force,
            ttl_sec=_unified_ttl_sec(),
            max_pairs=max_pairs,
            ingest_result_map=(ingest_cycle.pair_results if ingest_cycle is not None else None),
            global_data_watermark_before=(ingest_cycle.global_watermark_before if ingest_cycle is not None else None),
            global_data_watermark_after=(ingest_cycle.global_watermark_after if ingest_cycle is not None else None),
        )

    def _persist_unified_signal_run(max_pairs: int | None, *, force: bool, ingest_cycle=None) -> dict[str, object]:
        snapshot = _unified_snapshot(max_pairs=max_pairs, force=force, ingest_cycle=ingest_cycle)
        require_score_gate_signals = _default_require_score_gate_for_signals(settings)
        signals_all = snapshot.signals.copy()
        top_pairs = snapshot.top_pairs.copy()
        signals_actionable = _apply_score_gate_filter(
            signals_all.copy(),
            require_score_gate=require_score_gate_signals,
        )
        filtered_snapshot = UnifiedMarketSnapshot(
            created_at=snapshot.created_at,
            top_pairs=top_pairs,
            signals=signals_all,
            backtests=snapshot.backtests.copy(),
            warnings=list(snapshot.warnings),
            errors=list(snapshot.errors),
        )
        if settings.ui.signal_refresh_save_csv:
            persist_snapshot_to_csv(filtered_snapshot, paths.data_dir)
        run_id = f"signal-run-{uuid.uuid4().hex[:8]}"
        as_of = datetime.now(timezone.utc)
        params = {
            "max_pairs": max_pairs,
            "engine": "unified_minute_replay",
            "require_score_gate_signals": require_score_gate_signals,
            "require_score_gate_top_pairs": False,
            "signals_total": int(len(signals_all)),
            "signals_actionable": int(len(signals_actionable)),
            "warnings": list(snapshot.warnings),
            "errors": list(snapshot.errors),
        }
        records = signals_all.to_dict("records") if not signals_all.empty else []
        with session_factory() as session:
            store_signal_run(session, run_id, as_of, params)
            if records:
                store_signal_history(session, run_id, as_of, records)
        fallback_count = sum(1 for item in snapshot.warnings if ":fallback:" in str(item))
        return {
            "rows": int(len(signals_actionable)),
            "warnings": list(snapshot.warnings),
            "errors": list(snapshot.errors),
            "fallback_full_replay_count": int(fallback_count),
            "telemetry": get_last_refresh_telemetry(),
        }

    def _load_latest_unified_output(
        *,
        max_pairs: int | None,
        fresh: bool = False,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        top_pairs = pd.DataFrame()
        signals = pd.DataFrame()
        backtests = pd.DataFrame()
        # Default path: serve the latest backend-produced projection (last-good CSV outputs).
        if not fresh:
            top_pairs = load_top_pairs(paths.data_dir)
            signals = load_signals(paths.data_dir)
            backtests = load_backtest_summary(paths.data_dir)
        if top_pairs.empty or signals.empty or backtests.empty:
            snapshot = _unified_snapshot(max_pairs=max_pairs, force=False)
            if top_pairs.empty:
                top_pairs = snapshot.top_pairs.copy()
            if signals.empty:
                signals = snapshot.signals.copy()
            if backtests.empty:
                backtests = snapshot.backtests.copy()
        return top_pairs, signals, backtests

    def _run_signal_refresh(trigger: str, force: bool = False) -> bool:
        if not refresh_enabled and trigger != "manual":
            refresh_state["status"] = "disabled"
            refresh_state["last_error"] = f"skip:{trigger}"
            return False
        if refresh_lock.locked():
            refresh_state["status"] = "busy"
            refresh_state["last_error"] = f"skip:{trigger}"
            return False
        with refresh_lock:
            started = datetime.now(timezone.utc)
            refresh_state["status"] = "running"
            refresh_state["last_started_at"] = _iso_now()
            refresh_state["last_error"] = None
            try:
                if settings.ui.use_unified_signal_engine:
                    max_pairs = _resolved_unified_max_pairs(settings.ui.signal_refresh_max_pairs)
                    ingest_cycle = None
                    if incremental_enabled and not force:
                        ingest_pairs = list_unified_ingest_pairs(
                            settings,
                            paths.data_dir,
                            max_pairs=max_pairs,
                        )
                        ingest_cycle = run_incremental_minute_ingest(
                            settings=settings,
                            data_dir=paths.data_dir,
                            checkpoint_root=_resolve_incremental_checkpoint_root(),
                            pairs=ingest_pairs,
                            overlap_minutes=max(int(getattr(settings.ui, "incremental_overlap_minutes", 180) or 0), 1),
                        )
                        refresh_state["data_watermark_before"] = ingest_cycle.global_watermark_before
                        refresh_state["data_watermark_after"] = ingest_cycle.global_watermark_after
                        lag_values = [
                            float(item.ingest_lag_sec)
                            for item in ingest_cycle.pair_results.values()
                            if item.ingest_lag_sec is not None
                        ]
                        refresh_state["ingest_lag_sec"] = max(lag_values) if lag_values else None
                        if ingest_cycle.degraded:
                            observability.mark_event("incremental_ingest_degraded")
                    refresh_payload = _persist_unified_signal_run(
                        max_pairs,
                        force=force,
                        ingest_cycle=ingest_cycle,
                    )
                    refresh_state["rows"] = int(refresh_payload.get("rows") or 0)
                    refresh_state["engine"] = "unified_minute_replay"
                    refresh_state["fallback_full_replay_count"] = int(
                        refresh_payload.get("fallback_full_replay_count") or 0
                    )
                    telemetry = refresh_payload.get("telemetry")
                    if isinstance(telemetry, dict):
                        refresh_state["incremental_enabled"] = bool(
                            telemetry.get("incremental_enabled", incremental_enabled)
                        )
                        refresh_state["data_watermark_before"] = telemetry.get("data_watermark_before")
                        refresh_state["data_watermark_after"] = telemetry.get("data_watermark_after")
                        refresh_state["pairs_total"] = int(telemetry.get("pairs_total") or 0)
                        refresh_state["pairs_recomputed"] = int(telemetry.get("pairs_recomputed") or 0)
                        refresh_state["pairs_reused"] = int(telemetry.get("pairs_reused") or 0)
                        refresh_state["pairs_skipped"] = int(telemetry.get("pairs_skipped") or 0)
                        refresh_state["skip_reason"] = telemetry.get("skip_reason")
                        pairs_total = max(int(refresh_state["pairs_total"]), 1)
                        refresh_state["cache_hit_ratio"] = float(refresh_state["pairs_reused"]) / float(pairs_total)
                        if refresh_state["skip_reason"]:
                            observability.mark_event(
                                f"refresh_skip_{str(refresh_state['skip_reason']).strip().lower()}",
                            )
                    if refresh_state["fallback_full_replay_count"] > 0:
                        observability.mark_event(
                            "incremental_full_fallback",
                            count=int(refresh_state["fallback_full_replay_count"]),
                        )
                    degraded_mode = bool(ingest_cycle is not None and ingest_cycle.degraded)
                    if degraded_mode:
                        refresh_state["status"] = "degraded"
                    else:
                        refresh_state["status"] = "ok"
                        refresh_state["last_success_at"] = _iso_now()
                else:
                    run_signal_cycle(
                        settings,
                        max_pairs=settings.ui.signal_refresh_max_pairs,
                        save_csv=settings.ui.signal_refresh_save_csv,
                    )
                    refresh_state["engine"] = "legacy_pipeline"
                    refresh_state["status"] = "ok"
                    refresh_state["last_success_at"] = _iso_now()
            except Exception as exc:
                refresh_state["last_error"] = str(exc)
                refresh_state["status"] = "error"
                logger.exception("Signal refresh failed")
                return False
            finally:
                duration_ms = max((datetime.now(timezone.utc) - started).total_seconds() * 1000.0, 0.0)
                refresh_durations_ms.append(duration_ms)
                if len(refresh_durations_ms) > 500:
                    del refresh_durations_ms[: len(refresh_durations_ms) - 500]
                refresh_state["refresh_duration_ms_p50"] = _percentile(refresh_durations_ms, 50.0)
                refresh_state["refresh_duration_ms_p95"] = _percentile(refresh_durations_ms, 95.0)
                if refresh_state.get("status") == "degraded":
                    last_success = pd.to_datetime(refresh_state.get("last_success_at"), errors="coerce")
                    if not pd.isna(last_success):
                        refresh_state["staleness_age_sec"] = max(
                            (datetime.now(timezone.utc) - last_success.to_pydatetime().replace(tzinfo=timezone.utc)).total_seconds(),
                            0.0,
                        )
                    else:
                        refresh_state["staleness_age_sec"] = None
                else:
                    refresh_state["staleness_age_sec"] = 0.0
        return True

    def _refresh_loop() -> None:
        if refresh_daily_time is None and refresh_interval <= 0:
            return
        while not refresh_stop.is_set():
            if refresh_daily_time is not None:
                next_run = _next_daily_run(datetime.now(timezone.utc), refresh_daily_time, refresh_tz)
                refresh_state["next_run_at"] = next_run.isoformat().replace("+00:00", "Z")
                wait_seconds = max((next_run - datetime.now(timezone.utc)).total_seconds(), 0)
                if refresh_stop.wait(wait_seconds):
                    break
                _run_signal_refresh("daily")
            else:
                _run_signal_refresh("interval")
                refresh_state["next_run_at"] = (
                    datetime.now(timezone.utc) + timedelta(seconds=refresh_interval)
                ).isoformat().replace("+00:00", "Z")
                refresh_stop.wait(refresh_interval)

    if refresh_enabled and (refresh_daily_time is not None or refresh_interval > 0):
        refresh_state["status"] = "scheduled"
        thread = threading.Thread(
            target=_refresh_loop,
            name="signal-refresh",
            daemon=True,
        )
        thread.start()
        if refresh_daily_time is not None:
            logger.info("Signal refresh scheduler enabled (daily=%s)", settings.ui.signal_refresh_daily_time)
        else:
            logger.info("Signal refresh scheduler enabled (interval=%ss)", refresh_interval)

    @server.after_request
    def _cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"

        successor = _deprecated_v1_successor_path(request.path)
        if successor is not None:
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = _V1_DEPRECATION_SUNSET_HTTP
            response.headers["X-API-Deprecated"] = "v1"
            response.headers["X-API-Sunset-Date"] = _V1_DEPRECATION_SUNSET_DATE
            warning_text = (
                f'299 - "Deprecated API v1 endpoint; migrate to {successor} '
                f'before {_V1_DEPRECATION_SUNSET_DATE}"'
            )
            response.headers["Warning"] = warning_text
            link_value = f'<{successor}>; rel="successor-version"'
            existing_link = response.headers.get("Link")
            response.headers["Link"] = (
                f"{existing_link}, {link_value}" if existing_link else link_value
            )

        return response

    def _decision_exists(decision_id: str) -> bool:
        log_path = decisions_dir / "decision_log.jsonl"
        view_path = decisions_dir / "decision_view.jsonl"
        records = load_jsonl(log_path) if log_path.exists() else []
        if any(str(record.get("decision_id") or "") == decision_id for record in records):
            return True
        view_records = load_jsonl(view_path) if view_path.exists() else []
        return any(str(record.get("decision_id") or "") == decision_id for record in view_records)

    def _record_decision_action(
        decision_id: str,
        payload: dict[str, object],
        *,
        source_default: str,
        allowed_actions: set[str] | None = None,
    ):
        if not _decision_exists(decision_id):
            return jsonify({"error": "not_found"}), 404
        command, error = parse_decision_action_request(payload)
        if error is not None or command is None:
            return _bad_request(error or "invalid_action")
        if allowed_actions is not None and command.action not in allowed_actions:
            allowed = ", ".join(sorted(allowed_actions))
            return _bad_request(f"action must be one of: {allowed}")

        if not command.source:
            command.source = source_default
        idempotency_key = command.idempotency_key or f"idem-{uuid.uuid4().hex[:12]}"

        action_records = load_jsonl(actions_path) if actions_path.exists() else []
        execution_records = load_jsonl(executions_path) if executions_path.exists() else []
        for item in action_records:
            if str(item.get("decision_id") or "") != decision_id:
                continue
            existing_key = str(item.get("idempotency_key") or "").strip()
            if existing_key and existing_key == idempotency_key:
                execution_match = None
                for execution_item in execution_records:
                    if not isinstance(execution_item, dict):
                        continue
                    if str(execution_item.get("decision_id") or "") != decision_id:
                        continue
                    execution_key = str(execution_item.get("idempotency_key") or "").strip()
                    if execution_key and execution_key == idempotency_key:
                        execution_match = execution_item
                        break
                decision_ref = {
                    "decision_id": decision_id,
                    "action_id": item.get("action_id"),
                    "latest_action": item.get("action"),
                    "latest_status": item.get("status"),
                    "actor_id": item.get("actor"),
                    "source": item.get("source"),
                    "idempotency_key": item.get("idempotency_key"),
                    "updated_at": item.get("created_at"),
                }
                execution_ref = {
                    "request_id": execution_match.get("request_id")
                    if isinstance(execution_match, dict)
                    else None,
                    "action": execution_match.get("action")
                    if isinstance(execution_match, dict)
                    else None,
                    "status": execution_match.get("status")
                    if isinstance(execution_match, dict)
                    else None,
                    "requested_at": execution_match.get("requested_at")
                    if isinstance(execution_match, dict)
                    else None,
                    "executed_at": execution_match.get("executed_at")
                    if isinstance(execution_match, dict)
                    else None,
                    "actor_id": execution_match.get("actor")
                    if isinstance(execution_match, dict)
                    else None,
                    "source": execution_match.get("source")
                    if isinstance(execution_match, dict)
                    else None,
                    "reason_code": execution_match.get("reason_code")
                    if isinstance(execution_match, dict)
                    else None,
                    "idempotency_key": execution_match.get("idempotency_key")
                    if isinstance(execution_match, dict)
                    else None,
                }
                return jsonify(
                    {
                        "status": "duplicate",
                        "decision_id": decision_id,
                        "action_id": item.get("action_id"),
                        "idempotency_key": idempotency_key,
                        "operator_action": item,
                        "execution_status": execution_match or {},
                        "decision_ref": decision_ref,
                        "execution_ref": execution_ref,
                    }
                )

        created_at = _iso_now()
        action_id = _stable_id(
            "dact", decision_id, command.action, idempotency_key, created_at, length=20
        )
        request_id = _stable_id(
            "dreq", decision_id, command.action, idempotency_key, created_at, length=20
        )
        action_entry, execution_entry = build_decision_action_entries(
            decision_id=decision_id,
            action_id=action_id,
            request_id=request_id,
            created_at=created_at,
            command=command,
            idempotency_key=idempotency_key,
        )
        _append_jsonl(actions_path, action_entry)
        _append_jsonl(executions_path, execution_entry)

        return jsonify(
            {
                "status": "ok",
                "decision_id": decision_id,
                "action_id": action_id,
                "idempotency_key": idempotency_key,
                "operator_action": action_entry,
                "execution_status": execution_entry,
                "decision_ref": {
                    "decision_id": decision_id,
                    "action_id": action_entry.get("action_id"),
                    "latest_action": action_entry.get("action"),
                    "latest_status": action_entry.get("status"),
                    "actor_id": action_entry.get("actor"),
                    "source": action_entry.get("source"),
                    "idempotency_key": action_entry.get("idempotency_key"),
                    "updated_at": action_entry.get("created_at"),
                },
                "execution_ref": {
                    "request_id": execution_entry.get("request_id"),
                    "action": execution_entry.get("action"),
                    "status": execution_entry.get("status"),
                    "requested_at": execution_entry.get("requested_at"),
                    "executed_at": execution_entry.get("executed_at"),
                    "actor_id": execution_entry.get("actor"),
                    "source": execution_entry.get("source"),
                    "reason_code": execution_entry.get("reason_code"),
                    "idempotency_key": execution_entry.get("idempotency_key"),
                },
            }
        )

    @server.route("/api/signals/refresh-status", methods=["GET"])
    def signals_refresh_status_api():
        return jsonify(refresh_state)

    @server.route("/api/signals/refresh", methods=["POST"])
    def signals_refresh_api():
        if refresh_lock.locked():
            return jsonify({**refresh_state, "status": "busy"}), 409
        payload = request.get_json(silent=True)
        force_full = False
        if isinstance(payload, dict):
            force_full = bool(_parse_bool(payload.get("force_full")))
        elif request.args:
            force_full = bool(_parse_bool(request.args.get("force_full")))
        ok = _run_signal_refresh("manual", force=force_full)
        status_code = 200 if ok else 500
        return jsonify(refresh_state), status_code

    @server.route("/api/decision-view", methods=["GET"])
    def decision_view_api():
        limit = max(_parse_int(request.args.get("limit"), 500), 0)

        def _load_decision_view_jsonl_rows() -> list[dict[str, object]]:
            view_path = paths.data_dir / "decisions" / "decision_view.jsonl"
            records = load_jsonl(view_path)
            df = pd.DataFrame(records)
            df = _apply_query_filters(df, request.args)
            df = df.sort_values("created_at", ascending=False) if not df.empty else df
            if limit > 0:
                df = df.head(limit)
            return _df_to_records(df)

        projection_source = "jsonl"
        if settings.ui.ff_db_projection_source:
            with session_factory() as session:
                response_rows = load_decision_view_projection(
                    session,
                    limit=limit,
                    strategy_type=request.args.get("strategy_type"),
                    primary_instrument=request.args.get("primary_instrument"),
                    risk_state=request.args.get("risk_state"),
                    news_severity=request.args.get("news_severity"),
                    created_from=request.args.get("created_from"),
                    created_to=request.args.get("created_to"),
                )
            if response_rows:
                projection_source = "db"
            else:
                response_rows = _load_decision_view_jsonl_rows()
                projection_source = "jsonl_fallback"
        else:
            response_rows = _load_decision_view_jsonl_rows()

        action_records = load_jsonl(actions_path) if actions_path.exists() else []
        execution_records = load_jsonl(executions_path) if executions_path.exists() else []
        latest_actions = _latest_by_decision_id(action_records)
        latest_executions = _latest_by_decision_id(execution_records)
        for row in response_rows:
            decision_id = row.get("decision_id")
            if not decision_id:
                continue
            action = latest_actions.get(decision_id)
            if isinstance(action, dict):
                row["operator_action"] = {
                    "action_id": action.get("action_id"),
                    "action": action.get("action"),
                    "status": action.get("status"),
                    "actor": action.get("actor"),
                    "source": action.get("source"),
                    "reason_code": action.get("reason_code"),
                    "note": action.get("note"),
                    "comment": action.get("comment"),
                    "idempotency_key": action.get("idempotency_key"),
                    "created_at": action.get("created_at"),
                }
            execution = latest_executions.get(decision_id)
            if isinstance(execution, dict):
                row["execution_status"] = {
                    "request_id": execution.get("request_id"),
                    "action": execution.get("action"),
                    "status": execution.get("status"),
                    "requested_at": execution.get("requested_at"),
                    "executed_at": execution.get("executed_at"),
                    "actor": execution.get("actor"),
                    "source": execution.get("source"),
                    "reason_code": execution.get("reason_code"),
                    "note": execution.get("note"),
                    "idempotency_key": execution.get("idempotency_key"),
                }
            row["projection_source"] = projection_source
        return jsonify(response_rows)

    @server.route("/api/v2/decisions/view", methods=["GET"])
    @server.route("/api/v2/decision-view", methods=["GET"])
    def decision_view_v2_api():
        legacy = decision_view_api()
        rows, status_code = _extract_response_payload(legacy)
        if status_code >= 400:
            return legacy
        if not isinstance(rows, list):
            return jsonify([])
        projection_version = "v2.0"
        payload: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            decision_id = str(row.get("decision_id") or "").strip() or None
            primary = str(row.get("primary_instrument") or "").strip()
            operator_action = row.get("operator_action")
            execution_status = row.get("execution_status")
            operator_action = operator_action if isinstance(operator_action, dict) else {}
            execution_status = execution_status if isinstance(execution_status, dict) else {}
            entity_ref = {
                "entity_type": "instrument",
                "entity_id": primary,
                "ticker": primary or None,
            }
            decision_ref = {
                "decision_id": decision_id,
                "action_id": operator_action.get("action_id"),
                "latest_action": operator_action.get("action"),
                "latest_status": operator_action.get("status"),
                "actor_id": operator_action.get("actor"),
                "source": operator_action.get("source"),
                "idempotency_key": operator_action.get("idempotency_key"),
                "updated_at": operator_action.get("created_at"),
            }
            execution_ref = {
                "request_id": execution_status.get("request_id"),
                "action": execution_status.get("action"),
                "status": execution_status.get("status"),
                "requested_at": execution_status.get("requested_at"),
                "executed_at": execution_status.get("executed_at"),
                "actor_id": execution_status.get("actor"),
                "source": execution_status.get("source"),
                "reason_code": execution_status.get("reason_code"),
                "idempotency_key": execution_status.get("idempotency_key"),
            }
            enriched = dict(row)
            enriched["projection_version"] = projection_version
            enriched["decision_ref"] = decision_ref
            enriched["entity_ref"] = entity_ref
            enriched["execution_ref"] = execution_ref
            payload.append(enriched)
        return jsonify(payload)

    @server.route("/api/decision-log/<decision_id>", methods=["GET"])
    def decision_log_api(decision_id: str):
        log_path = paths.data_dir / "decisions" / "decision_log.jsonl"
        records = load_jsonl(log_path)
        for record in records:
            if record.get("decision_id") == decision_id:
                return jsonify(record)
        return jsonify({"error": "not_found"}), 404

    @server.route("/api/v2/news/feed", methods=["GET"])
    def news_feed_v2_api():
        severity_filter = str(request.args.get("severity") or "").strip().lower()
        ticker_filter = str(request.args.get("ticker") or "").strip().upper()
        entity_filter = str(request.args.get("entity_id") or "").strip()
        from_raw = request.args.get("from")
        to_raw = request.args.get("to")
        from_ts = _parse_date_bound(from_raw, "start") if from_raw else None
        to_ts = _parse_date_bound(to_raw, "end") if to_raw else None
        if from_raw and from_ts is None:
            return jsonify({"error": "invalid_from"}), 400
        if to_raw and to_ts is None:
            return jsonify({"error": "invalid_to"}), 400

        log_path = paths.data_dir / "decisions" / "decision_log.jsonl"
        view_path = paths.data_dir / "decisions" / "decision_view.jsonl"
        log_records = load_jsonl(log_path)
        view_records = load_jsonl(view_path)
        view_by_decision = {
            str(item.get("decision_id") or ""): item for item in view_records if isinstance(item, dict)
        }

        events: list[dict[str, object]] = []
        for record in log_records:
            if not isinstance(record, dict):
                continue
            decision_id = str(record.get("decision_id") or "").strip()
            created_at_raw = str(record.get("created_at") or "").strip()
            if not decision_id or not created_at_raw:
                continue
            try:
                created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            created_at_cmp = _normalize_datetime(created_at)
            if from_ts and created_at_cmp < from_ts:
                continue
            if to_ts and created_at_cmp > to_ts:
                continue

            news_context = record.get("news_context")
            if not isinstance(news_context, dict):
                continue
            severity = str(news_context.get("severity") or "low").strip().lower()
            if severity_filter and severity != severity_filter:
                continue

            view_row = view_by_decision.get(decision_id, {})
            primary = str(view_row.get("primary_instrument") or "").strip()
            entity_ref = {
                "entity_type": "instrument",
                "entity_id": primary,
                "ticker": primary or None,
            }
            if ticker_filter and ticker_filter not in {primary.upper(), str(entity_ref.get("ticker") or "").upper()}:
                continue
            if entity_filter and entity_filter != str(entity_ref.get("entity_id") or ""):
                continue

            summary = str(news_context.get("summary") or "news_signal").strip() or "news_signal"
            headline = str(news_context.get("headline") or summary).strip() or summary
            event_id = _stable_id("news", decision_id, created_at_raw, severity, headline, summary, length=20)
            events.append(
                {
                    "news_event_id": event_id,
                    "published_at": created_at_raw,
                    "severity": severity,
                    "headline": headline,
                    "summary": summary,
                    "headline_count": int(news_context.get("headline_count") or 0),
                    "decision_ref": {"decision_id": decision_id},
                    "entity_links": [entity_ref],
                }
            )

        events.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
        limit = _parse_int(request.args.get("limit"), 200)
        if limit > 0:
            events = events[:limit]
        return jsonify(events)

    @server.route("/api/decisions/<decision_id>/action", methods=["GET", "POST"])
    def decision_action_api(decision_id: str):
        if not _decision_exists(decision_id):
            return jsonify({"error": "not_found"}), 404
        if request.method == "GET":
            action_records = load_jsonl(actions_path) if actions_path.exists() else []
            latest_actions = _latest_by_decision_id(action_records)
            execution_records = load_jsonl(executions_path) if executions_path.exists() else []
            latest_executions = _latest_by_decision_id(execution_records)
            action = latest_actions.get(decision_id)
            execution = latest_executions.get(decision_id)
            return jsonify(
                {
                    "decision_id": decision_id,
                    "operator_action": action or {},
                    "execution_status": execution or {},
                }
            )
        payload = request.get_json(silent=True)
        if payload is None:
            return _bad_request("invalid_json")
        if not isinstance(payload, dict):
            return _bad_request("payload must be object")
        adapter_payload: dict[str, object] = dict(payload)
        adapter_payload["source"] = "v1_adapter"
        adapter_payload["actor_id"] = payload.get("actor") or payload.get("actor_id")
        adapter_payload["comment"] = payload.get("note") or payload.get("comment")
        return _record_decision_action(
            decision_id,
            adapter_payload,
            source_default="v1_adapter",
            allowed_actions={"APPROVE", "REJECT"},
        )

    @server.route("/api/v2/decisions/<decision_id>/actions", methods=["POST"])
    def decision_actions_v2_api(decision_id: str):
        payload = request.get_json(silent=True)
        if payload is None:
            return _bad_request("invalid_json")
        if not isinstance(payload, dict):
            return _bad_request("payload must be object")
        return _record_decision_action(
            decision_id,
            dict(payload),
            source_default="ui",
            allowed_actions={"APPROVE", "HOLD", "REJECT", "EXECUTE", "CLOSE"},
        )

    @server.route("/api/params/specs", methods=["GET"])
    def params_specs_api():
        preset = request.args.get("preset")
        try:
            specs = get_parameter_specs(preset)
        except ValueError as exc:
            return jsonify({"error": "unknown_preset", "message": str(exc)}), 400
        return jsonify([spec.model_dump() for spec in specs])

    @server.route("/api/backtest/run", methods=["POST"])
    def backtest_run_api():
        payload = request.get_json(silent=True)
        if payload is None:
            return _bad_request("invalid_json")
        precompute = None
        compute_fill_quality = None
        request_payload = payload
        if isinstance(payload, dict):
            if "request" in payload:
                request_payload = payload.get("request")
                precompute = _parse_bool(payload.get("precompute"))
                compute_fill_quality = _parse_bool(payload.get("compute_fill_quality"))
            elif "precompute" in payload:
                precompute = _parse_bool(payload.get("precompute"))
                request_payload = dict(payload)
                request_payload.pop("precompute", None)
                compute_fill_quality = _parse_bool(payload.get("compute_fill_quality"))
                request_payload.pop("compute_fill_quality", None)
            elif "compute_fill_quality" in payload:
                compute_fill_quality = _parse_bool(payload.get("compute_fill_quality"))
                request_payload = dict(payload)
                request_payload.pop("compute_fill_quality", None)
        if not isinstance(request_payload, dict):
            return _bad_request("missing_request")
        try:
            backtest_request = BacktestRequest.model_validate(request_payload)
        except ValidationError as exc:
            return _bad_request("validation_error", details=exc.errors())
        if compute_fill_quality is None:
            compute_fill_quality = True
        try:
            report = run_backtest_v2_cached(
                backtest_request,
                paths.data_dir,
                precompute=precompute,
                compute_fill_quality=compute_fill_quality,
            )
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            logger.exception("Backtest v2 failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500
        return jsonify(serialize_backtest_report(report))

    @server.route("/api/forward/start", methods=["POST"])
    def forward_start_api():
        payload = request.get_json(silent=True) or {}
        request_payload = payload
        if isinstance(payload, dict) and "request" in payload:
            request_payload = payload.get("request") or {}
        if not isinstance(request_payload, dict):
            return _bad_request("missing_request")
        try:
            forward_request = ForwardTestRequest.model_validate(request_payload)
        except ValidationError as exc:
            return _bad_request("validation_error", details=exc.errors())
        try:
            run_info = start_forward_run(forward_request, paths.data_dir)
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            logger.exception("Forward start failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500
        return jsonify(run_info)

    @server.route("/api/forward/status", methods=["GET"])
    def forward_status_api():
        run_id = request.args.get("run_id")
        try:
            status = load_forward_status(paths.data_dir, run_id=run_id)
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            logger.exception("Forward status failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500
        return jsonify(status)

    @server.route("/api/hpo/run", methods=["POST"])
    def hpo_run_api():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _bad_request("invalid_json")
        precompute = _parse_bool(payload.get("precompute"))
        if precompute is None:
            precompute = True
        request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else payload
        if not isinstance(request_payload, dict):
            return _bad_request("missing_request")
        request_payload = {key: value for key, value in request_payload.items() if key != "precompute"}
        optimization = request_payload.get("optimization") if isinstance(request_payload, dict) else None
        max_trials_override = None
        if not (isinstance(optimization, dict) and "max_trials" in optimization):
            max_trials_override = 10
        try:
            hpo_request = HpoRequest.model_validate(request_payload)
        except ValidationError as exc:
            return _bad_request("validation_error", details=exc.errors())
        try:
            run_info = start_hpo_run(
                hpo_request,
                paths.data_dir,
                precompute=precompute,
                max_trials_override=max_trials_override,
            )
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            logger.exception("HPO run failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500
        return jsonify(run_info)

    @server.route("/api/hpo/status", methods=["GET"])
    def hpo_status_api():
        run_id = request.args.get("run_id")
        try:
            status = load_hpo_status(paths.data_dir, run_id=run_id)
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            logger.exception("HPO status failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500
        return jsonify(status)

    @server.route("/api/v2/research/backtests/run", methods=["POST"])
    def backtest_run_v2_api():
        payload = request.get_json(silent=True)
        if payload is None or not isinstance(payload, dict):
            return _bad_request("invalid_json")
        experiment_id = str(payload.get("experiment_id") or f"exp-{uuid.uuid4().hex[:12]}")
        precompute = _parse_bool(payload.get("precompute"))
        compute_fill_quality = _parse_bool(payload.get("compute_fill_quality"))
        if precompute is None:
            precompute = True
        if compute_fill_quality is None:
            compute_fill_quality = True
        request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else payload
        if not isinstance(request_payload, dict):
            return _bad_request("missing_request")
        request_payload = {
            key: value
            for key, value in request_payload.items()
            if key not in {"precompute", "compute_fill_quality"}
        }
        try:
            backtest_request = BacktestRequest.model_validate(request_payload)
        except ValidationError as exc:
            return _bad_request("validation_error", details=exc.errors())
        try:
            report = run_backtest_v2_cached(
                backtest_request,
                paths.data_dir,
                precompute=precompute,
                compute_fill_quality=compute_fill_quality,
            )
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            logger.exception("Backtest v2 failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500

        request_hash = hashlib.sha1(
            json.dumps(request_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return jsonify(
            {
                "experiment_id": experiment_id,
                "run_id": f"bt-{uuid.uuid4().hex[:12]}",
                "request_hash": request_hash,
                "status": "completed",
                "report": serialize_backtest_report(report),
            }
        )

    @server.route("/api/v2/research/hpo/run", methods=["POST"])
    def hpo_run_v2_api():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _bad_request("invalid_json")
        experiment_id = str(payload.get("experiment_id") or f"exp-{uuid.uuid4().hex[:12]}")
        precompute = _parse_bool(payload.get("precompute"))
        if precompute is None:
            precompute = True
        request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else payload
        if not isinstance(request_payload, dict):
            return _bad_request("missing_request")
        request_payload = {key: value for key, value in request_payload.items() if key != "precompute"}
        optimization = request_payload.get("optimization") if isinstance(request_payload, dict) else None
        max_trials_override = None
        if not (isinstance(optimization, dict) and "max_trials" in optimization):
            max_trials_override = 10
        try:
            hpo_request = HpoRequest.model_validate(request_payload)
        except ValidationError as exc:
            return _bad_request("validation_error", details=exc.errors())
        try:
            run_info = start_hpo_run(
                hpo_request,
                paths.data_dir,
                precompute=precompute,
                max_trials_override=max_trials_override,
            )
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            logger.exception("HPO run failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500

        request_hash = hashlib.sha1(
            json.dumps(request_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return jsonify(
            {
                **run_info,
                "experiment_id": experiment_id,
                "request_hash": request_hash,
            }
        )

    @server.route("/api/v2/research/hpo/status", methods=["GET"])
    def hpo_status_v2_api():
        run_id = request.args.get("run_id")
        try:
            status = load_hpo_status(paths.data_dir, run_id=run_id)
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            logger.exception("HPO status failed")
            return jsonify({"error": "server_error", "message": str(exc)}), 500

        payload = dict(status) if isinstance(status, dict) else {"status": "unknown"}
        run_state = str(payload.get("status") or "").lower()
        result = payload.get("result")
        leaderboard = []
        quality_review = None
        if isinstance(result, dict):
            raw = result.get("leaderboard")
            if isinstance(raw, list):
                leaderboard = raw
            quality_candidate = result.get("quality_review")
            if isinstance(quality_candidate, dict):
                quality_review = quality_candidate
        if not leaderboard and isinstance(payload.get("leaderboard"), list):
            leaderboard = payload.get("leaderboard")

        quality_checks: list[str] = []
        if isinstance(quality_review, dict) and not bool(quality_review.get("skipped")):
            pass_count = int(quality_review.get("quality_gate_pass_count") or 0)
            if pass_count > 0:
                quality_checks.append("quality_gate_pass")
            else:
                quality_checks.append("quality_gate_fail")

        if run_state == "completed" and leaderboard and ("quality_gate_fail" not in quality_checks):
            promotion_gate = {"status": "pass", "checks": ["leaderboard_present", "completed"]}
            if quality_checks:
                promotion_gate["checks"].extend(quality_checks)
        elif run_state == "completed" and "quality_gate_fail" in quality_checks:
            promotion_gate = {"status": "fail", "checks": ["quality_gate_fail", "leaderboard_present"]}
        elif run_state == "completed":
            promotion_gate = {"status": "fail", "checks": ["leaderboard_missing"]}
        elif run_state == "failed":
            promotion_gate = {"status": "fail", "checks": ["run_failed"]}
        else:
            promotion_gate = {"status": "pending", "checks": ["run_in_progress"]}
        payload["promotion_gate"] = promotion_gate
        return jsonify(payload)

    @server.route("/api/v2/top-pairs", methods=["GET"])
    @server.route("/api/top-pairs", methods=["GET"])
    def top_pairs_api():
        all_pairs = request.args.get("all", "").lower() in {"1", "true", "yes"}
        fresh = request.args.get("fresh", "").lower() in {"1", "true", "yes"}
        require_score_gate = _resolve_require_score_gate(
            request.args.get("require_score_gate"),
            default=_default_require_score_gate_for_top_pairs(settings),
        )
        limit = int(request.args.get("limit", "500"))
        df = pd.DataFrame()
        if settings.ui.use_unified_signal_engine:
            try:
                max_pairs = None if all_pairs else _resolved_unified_max_pairs(limit)
                top_pairs, _, _ = _load_latest_unified_output(
                    max_pairs=max_pairs,
                    fresh=fresh,
                )
                df = top_pairs.copy()
            except Exception:
                logger.exception("Unified top-pairs failed")
                if not settings.ui.unified_allow_legacy_fallback:
                    return jsonify({"error": "server_error", "message": "unified_top_pairs_failed"}), 500
        if df.empty and settings.ui.unified_allow_legacy_fallback:
            df = load_top_pairs(paths.data_dir)
        df = _apply_score_gate_filter(df, require_score_gate=require_score_gate)
        if not df.empty and "signal_score_norm" not in df.columns:
            if {"zscore", "implied_rate_net", "required_rate"}.issubset(df.columns):
                z_entry = settings.strategy.z_entry
                implied_buffer = settings.strategy.implied_rate_buffer
                z_component = df["zscore"].abs() / z_entry if z_entry else 0.0
                rate_gap = (df["implied_rate_net"] - df["required_rate"]).abs()
                rate_component = rate_gap / implied_buffer if implied_buffer else 0.0
                df["signal_score_norm"] = 0.5 * (z_component + rate_component)
        if not all_pairs:
            df = df.head(max(limit, 0)) if limit else df
        records = [_merge_signal_metrics(record) for record in _df_to_records(df)]
        for record in records:
            record["execution_quality"] = _build_execution_quality(record)
        return jsonify(records)

    @server.route("/api/signals", methods=["GET"])
    def signals_api():
        df = pd.DataFrame()
        fresh = request.args.get("fresh", "").lower() in {"1", "true", "yes"}
        require_score_gate = _resolve_require_score_gate(
            request.args.get("require_score_gate"),
            default=_default_require_score_gate_for_signals(settings),
        )
        if settings.ui.use_unified_signal_engine:
            limit = int(request.args.get("limit", "500"))
            try:
                _, signals, _ = _load_latest_unified_output(
                    max_pairs=_resolved_unified_max_pairs(limit),
                    fresh=fresh,
                )
                df = signals.copy()
            except Exception:
                logger.exception("Unified signals failed")
                if not settings.ui.unified_allow_legacy_fallback:
                    return jsonify({"error": "server_error", "message": "unified_signals_failed"}), 500
        if df.empty and settings.ui.unified_allow_legacy_fallback:
            df = load_signals(paths.data_dir)
        df = _apply_score_gate_filter(df, require_score_gate=require_score_gate)
        limit = int(request.args.get("limit", "500"))
        df = df.head(max(limit, 0)) if limit else df
        records = [_merge_signal_metrics(record) for record in _df_to_records(df)]
        for record in records:
            record["execution_quality"] = _build_execution_quality(record)
        return jsonify(records)

    @server.route("/api/signals/active", methods=["GET"])
    def signals_active_api():
        require_score_gate = _resolve_require_score_gate(
            request.args.get("require_score_gate"),
            default=_default_require_score_gate_for_signals(settings),
        )
        with session_factory() as session:
            latest = load_latest_signal_run(session)
            if not latest:
                return jsonify([])
            rows = load_active_signals(session, latest.run_id)
            executions = load_open_executions(session)
            ack_by_fingerprint: dict[str, dict[str, object]] = {}
            pair_trade_timestamps: dict[tuple[str, str], list[datetime]] = {}
            position_state: dict[tuple[str, str], dict[str, object]] = {}
            for exec_row in sorted(executions, key=lambda item: item.timestamp):
                if not isinstance(exec_row.timestamp, datetime):
                    continue
                exec_ts = _normalize_datetime(exec_row.timestamp)
                key = (exec_row.stock_secid, exec_row.future_secid)
                state = position_state.setdefault(
                    key,
                    {
                        "enter_count": 0,
                        "exit_count": 0,
                        "net_executions": 0,
                        "last_execution_at": None,
                        "direction": None,
                        "open_legs": {"stock": 0, "future": 0, "other": 0},
                        "enter_orders": set(),
                        "exit_orders": set(),
                        "order_legs": {},
                    },
                )
                action = _normalize_execution_action(exec_row.action)
                if action == "ack":
                    ack_note = parse_ack_note(exec_row.note)
                    if isinstance(ack_note, dict):
                        fingerprint_raw = ack_note.get("fingerprint")
                        if isinstance(fingerprint_raw, str) and fingerprint_raw.strip():
                            fingerprint = fingerprint_raw.strip()
                            existing = ack_by_fingerprint.get(fingerprint)
                            existing_ts_raw = existing.get("timestamp") if isinstance(existing, dict) else None
                            existing_ts = (
                                _normalize_datetime(existing_ts_raw)
                                if isinstance(existing_ts_raw, datetime)
                                else None
                            )
                            if existing_ts is None or exec_ts >= existing_ts:
                                ack_by_fingerprint[fingerprint] = {
                                    "timestamp": exec_ts,
                                    "used_by": _signal_used_by_from_ack(ack_note),
                                }
                    continue
                if action not in {"enter", "exit"}:
                    continue
                pair_trade_timestamps.setdefault(key, []).append(exec_ts)
                leg = _normalize_execution_leg(exec_row.side)
                order_id = _normalize_order_id(getattr(exec_row, "order_id", None))
                if order_id is None:
                    order_id = f"legacy-{exec_row.id}"

                open_legs_raw = state.get("open_legs")
                if isinstance(open_legs_raw, dict):
                    open_legs = {
                        "stock": int(open_legs_raw.get("stock", 0) or 0),
                        "future": int(open_legs_raw.get("future", 0) or 0),
                        "other": int(open_legs_raw.get("other", 0) or 0),
                    }
                else:
                    open_legs = {"stock": 0, "future": 0, "other": 0}

                order_legs_raw = state.get("order_legs")
                order_legs: dict[tuple[str, str], set[str]]
                if isinstance(order_legs_raw, dict):
                    order_legs = {}
                    for order_key, value in order_legs_raw.items():
                        if (
                            isinstance(order_key, tuple)
                            and len(order_key) == 2
                            and isinstance(order_key[0], str)
                            and isinstance(order_key[1], str)
                            and isinstance(value, set)
                        ):
                            order_legs[order_key] = set(str(item) for item in value)
                else:
                    order_legs = {}
                group_key = (action, order_id)
                group_legs = order_legs.setdefault(group_key, set())
                group_legs.add(leg)
                state["order_legs"] = order_legs

                enter_orders_raw = state.get("enter_orders")
                enter_orders = set(enter_orders_raw) if isinstance(enter_orders_raw, set) else set()
                exit_orders_raw = state.get("exit_orders")
                exit_orders = set(exit_orders_raw) if isinstance(exit_orders_raw, set) else set()

                if action == "enter":
                    state["enter_count"] = int(state["enter_count"]) + 1
                    state["net_executions"] = int(state["net_executions"]) + 1
                    open_legs[leg] = int(open_legs.get(leg, 0)) + 1
                    enter_orders.add(order_id)
                elif action == "exit":
                    state["exit_count"] = int(state["exit_count"]) + 1
                    state["net_executions"] = max(int(state["net_executions"]) - 1, 0)
                    _decrement_leg_bucket(open_legs, leg)
                    exit_orders.add(order_id)
                state["open_legs"] = open_legs
                state["enter_orders"] = enter_orders
                state["exit_orders"] = exit_orders
                state["open_leg_total"] = int(open_legs["stock"] + open_legs["future"] + open_legs["other"])
                state["open_leg_imbalance"] = int(open_legs["stock"]) != int(open_legs["future"])
                state["last_execution_at"] = exec_ts
                if exec_row.direction is not None:
                    state["direction"] = exec_row.direction

            def _signal_usage_fields(
                *,
                run_id: str,
                timestamp: str,
                stock: str,
                future: str,
                signal_action: str,
            ) -> dict[str, object]:
                fingerprint = build_signal_fingerprint(
                    run_id=run_id,
                    timestamp=timestamp,
                    stock=stock,
                    future=future,
                    signal_action=signal_action,
                )
                ack_entry = ack_by_fingerprint.get(fingerprint)
                if not isinstance(ack_entry, dict):
                    return {
                        "signal_used": False,
                        "signal_used_at": None,
                        "signal_used_by": None,
                        "signal_details_pending": False,
                    }
                ack_ts_raw = ack_entry.get("timestamp")
                ack_ts = _normalize_datetime(ack_ts_raw) if isinstance(ack_ts_raw, datetime) else None
                has_trade_after_ack = False
                if ack_ts is not None:
                    trades = pair_trade_timestamps.get((stock, future), [])
                    has_trade_after_ack = any(trade_ts > ack_ts for trade_ts in trades)
                return {
                    "signal_used": True,
                    "signal_used_at": ack_ts.isoformat() if ack_ts is not None else None,
                    "signal_used_by": ack_entry.get("used_by"),
                    "signal_details_pending": not has_trade_after_ack,
                }

            for state in position_state.values():
                enter_orders = state.get("enter_orders")
                exit_orders = state.get("exit_orders")
                order_legs = state.get("order_legs")
                enter_order_count = len(enter_orders) if isinstance(enter_orders, set) else 0
                exit_order_count = len(exit_orders) if isinstance(exit_orders, set) else 0
                linked_two_leg_orders = 0
                partial_leg_orders = 0
                if isinstance(order_legs, dict):
                    for legs in order_legs.values():
                        if not isinstance(legs, set):
                            continue
                        normalized_legs = {str(leg) for leg in legs}
                        dual_leg = "stock" in normalized_legs and "future" in normalized_legs
                        single_leg = (
                            ("stock" in normalized_legs) ^ ("future" in normalized_legs)
                        )
                        if dual_leg:
                            linked_two_leg_orders += 1
                        elif single_leg:
                            partial_leg_orders += 1
                state["enter_order_count"] = enter_order_count
                state["exit_order_count"] = exit_order_count
                state["net_orders"] = max(enter_order_count - exit_order_count, 0)
                state["linked_two_leg_orders"] = linked_two_leg_orders
                state["partial_leg_orders"] = partial_leg_orders

            open_pairs = {
                key for key, state in position_state.items() if int(state.get("open_leg_total") or 0) > 0
            }
            rows_by_pair = {(row.stock_secid, row.future_secid): row for row in rows}
            actionable: list[dict[str, object]] = []
            for row in rows:
                key = (row.stock_secid, row.future_secid)
                state = position_state.get(key, {})
                is_open = key in open_pairs
                open_legs_raw = state.get("open_legs")
                open_legs = (
                    open_legs_raw
                    if isinstance(open_legs_raw, dict)
                    else {"stock": 0, "future": 0, "other": 0}
                )
                if row.action == "enter" and not is_open:
                    action = "enter"
                elif row.action == "exit" and is_open:
                    action = "exit"
                elif is_open:
                    action = "hold_open"
                else:
                    continue
                usage_fields = _signal_usage_fields(
                    run_id=row.run_id,
                    timestamp=row.timestamp.isoformat(),
                    stock=row.stock_secid,
                    future=row.future_secid,
                    signal_action=action,
                )
                payload = {
                    "run_id": row.run_id,
                    "timestamp": row.timestamp.isoformat(),
                    "stock": row.stock_secid,
                    "future": row.future_secid,
                    "signal_action": action,
                    "signal_direction": row.direction,
                    "signal_score": row.score,
                    "signal_reasons": row.reasons,
                    "signal_metrics": row.metrics,
                    "position_open": is_open,
                    "position_state": "open" if is_open else "flat",
                    "position_enter_count": int(state.get("enter_count") or 0),
                    "position_exit_count": int(state.get("exit_count") or 0),
                    "position_net_executions": int(state.get("net_executions") or 0),
                    "position_enter_order_count": int(state.get("enter_order_count") or 0),
                    "position_exit_order_count": int(state.get("exit_order_count") or 0),
                    "position_net_orders": int(state.get("net_orders") or 0),
                    "position_linked_two_leg_orders": int(state.get("linked_two_leg_orders") or 0),
                    "position_partial_leg_orders": int(state.get("partial_leg_orders") or 0),
                    "position_open_stock_legs": int(open_legs.get("stock") or 0),
                    "position_open_future_legs": int(open_legs.get("future") or 0),
                    "position_open_other_legs": int(open_legs.get("other") or 0),
                    "position_open_leg_total": int(state.get("open_leg_total") or 0),
                    "position_leg_imbalance": bool(state.get("open_leg_imbalance")),
                    "position_last_execution_at": (
                        state["last_execution_at"].isoformat()
                        if isinstance(state.get("last_execution_at"), datetime)
                        else None
                    ),
                    **usage_fields,
                }
                actionable.append(_merge_signal_metrics(payload))

            missing_open_pairs = open_pairs.difference(rows_by_pair.keys())
            for stock, future in sorted(missing_open_pairs):
                state = position_state.get((stock, future), {})
                open_legs_raw = state.get("open_legs")
                open_legs = (
                    open_legs_raw
                    if isinstance(open_legs_raw, dict)
                    else {"stock": 0, "future": 0, "other": 0}
                )
                last_execution_at = state.get("last_execution_at")
                if isinstance(last_execution_at, datetime):
                    timestamp_value = last_execution_at.isoformat()
                else:
                    timestamp_value = latest.as_of.isoformat()
                usage_fields = _signal_usage_fields(
                    run_id=latest.run_id,
                    timestamp=timestamp_value,
                    stock=stock,
                    future=future,
                    signal_action="hold_open",
                )
                payload = {
                    "run_id": latest.run_id,
                    "timestamp": timestamp_value,
                    "stock": stock,
                    "future": future,
                    "signal_action": "hold_open",
                    "signal_direction": state.get("direction"),
                    "signal_score": 0.0,
                    "signal_reasons": ["position_open_no_active_signal"],
                    "signal_metrics": {},
                    "position_open": True,
                    "position_state": "open",
                    "position_enter_count": int(state.get("enter_count") or 0),
                    "position_exit_count": int(state.get("exit_count") or 0),
                    "position_net_executions": int(state.get("net_executions") or 0),
                    "position_enter_order_count": int(state.get("enter_order_count") or 0),
                    "position_exit_order_count": int(state.get("exit_order_count") or 0),
                    "position_net_orders": int(state.get("net_orders") or 0),
                    "position_linked_two_leg_orders": int(state.get("linked_two_leg_orders") or 0),
                    "position_partial_leg_orders": int(state.get("partial_leg_orders") or 0),
                    "position_open_stock_legs": int(open_legs.get("stock") or 0),
                    "position_open_future_legs": int(open_legs.get("future") or 0),
                    "position_open_other_legs": int(open_legs.get("other") or 0),
                    "position_open_leg_total": int(state.get("open_leg_total") or 0),
                    "position_leg_imbalance": bool(state.get("open_leg_imbalance")),
                    "position_last_execution_at": (
                        last_execution_at.isoformat() if isinstance(last_execution_at, datetime) else None
                    ),
                    **usage_fields,
                }
                actionable.append(_merge_signal_metrics(payload))

            if require_score_gate:
                actionable = [
                    row
                    for row in actionable
                    if bool(row.get("position_open")) or _record_score_gate_pass(row)
                ]

            actionable.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
            actionable.sort(key=lambda item: 0 if bool(item.get("position_open")) else 1)
            return jsonify(actionable)

    @server.route("/api/v2/signals/active", methods=["GET"])
    def signals_active_v2_api():
        legacy = signals_active_api()
        rows, status_code = _extract_response_payload(legacy)
        if status_code >= 400:
            return legacy
        if not isinstance(rows, list):
            return jsonify([])

        payload: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            signal_id = _build_signal_id_from_row(row)
            lifecycle_state = _derive_lifecycle_state(row)
            entity_ref = _build_pair_entity_ref(row.get("stock"), row.get("future"))
            gate_results = _build_gate_results_from_row(row, signal_id)
            execution_ref = {
                "position_open": bool(row.get("position_open")),
                "position_state": row.get("position_state"),
                "last_execution_at": row.get("position_last_execution_at"),
                "open_leg_total": int(row.get("position_open_leg_total") or 0),
                "net_orders": int(row.get("position_net_orders") or 0),
            }
            enriched_row = dict(row)
            enriched_row.update(
                {
                    "signal_id": signal_id,
                    "entity_ref": entity_ref,
                    "lifecycle_state": lifecycle_state,
                    "signal_action_effective": _derive_effective_signal_action(row),
                    "gate_results": gate_results,
                    "decision_ref": {"decision_id": None},
                    "execution_ref": execution_ref,
                }
            )
            payload.append(enriched_row)
        return jsonify(payload)

    def _record_signal_action(
        signal_id: str | None,
        payload: dict[str, object],
        *,
        source_default: str,
        legacy_mode: bool = False,
    ):
        action_pair = _coerce_signal_action_request(payload.get("action"), legacy_mode=legacy_mode)
        if action_pair is None:
            if legacy_mode:
                return _bad_request("action must be one of: enter, exit, hold_open")
            return _bad_request("action must be one of: ack, enter, exit, hold")
        requested_action, execution_action = action_pair

        source = _normalize_signal_action_source(payload.get("source"), default=source_default)
        actor_id = str(payload.get("actor_id") or payload.get("actor") or "operator").strip() or "operator"
        reason_code_raw = payload.get("reason_code")
        reason_code = str(reason_code_raw).strip() if reason_code_raw is not None else None
        if reason_code == "":
            reason_code = None
        fail_closed_override = bool(_parse_bool(payload.get("fail_closed_override")))
        override_reason_raw = payload.get("override_reason")
        override_reason = (
            str(override_reason_raw).strip() if override_reason_raw is not None else (reason_code or None)
        )
        if override_reason == "":
            override_reason = None
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not idempotency_key:
            idempotency_key = f"idem-{uuid.uuid4().hex[:12]}"

        signal_row = None
        if signal_id:
            legacy = signals_active_api()
            rows, status_code = _extract_response_payload(legacy)
            if status_code >= 400:
                return legacy
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict) and _build_signal_id_from_row(row) == signal_id:
                        signal_row = row
                        break

        stock = str(payload.get("stock") or (signal_row or {}).get("stock") or "").strip()
        future = str(payload.get("future") or (signal_row or {}).get("future") or "").strip()
        if not stock or not future:
            message = "signal_id is unknown in active set" if signal_id else "stock and future are required"
            return jsonify({"error": "not_found", "message": message}), 404
        direction = payload.get("direction") or (signal_row or {}).get("signal_direction")
        signal_id_resolved = signal_id or _stable_id("sig", stock, future, requested_action)

        pretrade_payload = payload.get("pretrade")
        pretrade_status_hint = payload.get("pretrade_status")
        pretrade_degraded_hint = _parse_bool(payload.get("pretrade_degraded"))
        if isinstance(pretrade_payload, dict):
            if pretrade_status_hint is None:
                pretrade_status_hint = pretrade_payload.get("pretrade_status") or pretrade_payload.get("status")
            if pretrade_degraded_hint is None:
                pretrade_degraded_hint = _parse_bool(pretrade_payload.get("degraded"))

        fail_closed = evaluate_fail_closed_entry(
            enabled=bool(settings.ui.ff_fail_closed_execution),
            requested_action=requested_action,
            signal_row=signal_row if isinstance(signal_row, dict) else None,
            source=source,
            override=fail_closed_override,
            override_reason=override_reason,
            pretrade_status=pretrade_status_hint,
            pretrade_degraded=pretrade_degraded_hint,
        )
        if fail_closed.status == "block":
            return (
                jsonify(
                    {
                        "status": "blocked",
                        "error": "fail_closed_execution",
                        "signal_id": signal_id_resolved,
                        "entity_ref": _build_pair_entity_ref(stock, future),
                        "action": requested_action,
                        "reason_code": fail_closed.reason_code,
                        "message": fail_closed.message,
                        "fail_closed": {
                            "enabled": bool(settings.ui.ff_fail_closed_execution),
                            "status": fail_closed.status,
                            "reason_code": fail_closed.reason_code,
                        },
                    }
                ),
                409,
            )

        side = payload.get("side")
        order_id = _normalize_order_id(payload.get("order_id"))
        if order_id is None and execution_action in {"enter", "exit", "hold_open"}:
            leg = _normalize_execution_leg(side)
            if leg in {"stock", "future"}:
                order_id = f"{stock}-{future}-{execution_action}-{uuid.uuid4().hex[:10]}"

        note_payload: dict[str, object] = {
            "kind": "signal_action_v1_adapter" if legacy_mode else "signal_action_v2",
            "signal_id": signal_id_resolved,
            "source": source,
            "actor_id": actor_id,
            "idempotency_key": idempotency_key,
            "requested_action": requested_action,
        }
        if reason_code is not None:
            note_payload["reason_code"] = reason_code
        if fail_closed.status == "override":
            note_payload["fail_closed_override"] = True
            note_payload["fail_closed_reason"] = fail_closed.reason_code
        operator_note = payload.get("note") or payload.get("comment")
        if operator_note is not None and str(operator_note).strip():
            note_payload["note"] = str(operator_note).strip()
        note = json.dumps(note_payload, ensure_ascii=False, separators=(",", ":"))

        now = datetime.now(timezone.utc)
        action_id = f"act-{uuid.uuid4().hex[:12]}"

        with session_factory() as session:
            recent = load_signal_executions(session, stock=stock, future=future, limit=500)
            for row in recent:
                existing_key = _extract_idempotency_key(row.note)
                if existing_key and existing_key == idempotency_key:
                    return jsonify(
                        {
                            "status": "duplicate",
                            "action_id": f"act-{row.id}",
                            "signal_id": signal_id_resolved,
                            "entity_ref": _build_pair_entity_ref(stock, future),
                            "execution_event_id": f"exec-{row.id}",
                            "action": requested_action,
                            "idempotency_key": idempotency_key,
                            "order_id": row.order_id,
                            "fail_closed": {
                                "enabled": bool(settings.ui.ff_fail_closed_execution),
                                "status": fail_closed.status,
                                "reason_code": fail_closed.reason_code,
                            },
                        }
                    )

            status = payload.get("status")
            if status is None:
                status = "acknowledged" if requested_action == "ack" else "recorded"
            store_signal_execution(
                session,
                now,
                {
                    "stock": stock,
                    "future": future,
                    "direction": direction,
                    "action": execution_action,
                    "price": payload.get("price"),
                    "quantity": payload.get("quantity"),
                    "side": side,
                    "order_id": order_id,
                    "status": status,
                    "note": note,
                },
            )

        return jsonify(
            {
                "status": "ok",
                "action_id": action_id,
                "signal_id": signal_id_resolved,
                "entity_ref": _build_pair_entity_ref(stock, future),
                "execution_event_id": _stable_id(
                    "exec",
                    signal_id_resolved,
                    idempotency_key,
                    requested_action,
                    now.isoformat(),
                    length=20,
                ),
                "action": requested_action,
                "source": source,
                "actor_id": actor_id,
                "idempotency_key": idempotency_key,
                "stored_action": execution_action,
                "order_id": order_id,
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "fail_closed": {
                    "enabled": bool(settings.ui.ff_fail_closed_execution),
                    "status": fail_closed.status,
                    "reason_code": fail_closed.reason_code,
                },
            }
        )

    @server.route("/api/v2/signals/<signal_id>/actions", methods=["POST"])
    def signals_actions_v2_api(signal_id: str):
        started_at = datetime.now(timezone.utc)
        payload = request.get_json(silent=True)
        if payload is None or not isinstance(payload, dict):
            return _observe_request("v2_signals_actions", started_at, _bad_request("invalid_json"))
        result = _record_signal_action(
            signal_id,
            dict(payload),
            source_default="ui",
            legacy_mode=False,
        )
        _mark_signal_action_events(result)
        return _observe_request("v2_signals_actions", started_at, result)

    @server.route("/api/v2/policies/auto-unwind/run", methods=["POST"])
    def auto_unwind_run_v2_api():
        started_at = datetime.now(timezone.utc)

        def _finish(result):
            _mark_auto_unwind_events(result)
            return _observe_request("v2_auto_unwind_run", started_at, result)

        payload = request.get_json(silent=True)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return _finish(_bad_request("payload must be object"))

        timeout_default = max(int(getattr(settings.ui, "auto_unwind_timeout_sec", 600) or 600), 0)
        timeout_sec = max(_parse_int(payload.get("timeout_sec"), timeout_default), 0)
        dry_run_raw = _parse_bool(payload.get("dry_run"))
        dry_run = bool(dry_run_raw) if dry_run_raw is not None else False
        actor_id = str(payload.get("actor_id") or "system:auto-unwind").strip() or "system:auto-unwind"

        now_utc = datetime.now(timezone.utc)
        now_override = payload.get("now_utc")
        if now_override is not None and str(now_override).strip():
            try:
                parsed_now = datetime.fromisoformat(str(now_override).strip().replace("Z", "+00:00"))
            except ValueError:
                return _finish(_bad_request("now_utc must be ISO-8601 datetime"))
            now_utc = (
                parsed_now.replace(tzinfo=timezone.utc)
                if parsed_now.tzinfo is None
                else parsed_now.astimezone(timezone.utc)
            )

        active = signals_active_api()
        rows, status_code = _extract_response_payload(active)
        if status_code >= 400:
            return _finish(active)
        rows_list: list[dict[str, object]] = []
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    rows_list.append(row)

        candidates = select_auto_unwind_candidates(rows_list, timeout_sec=timeout_sec, now_utc=now_utc)
        rows_by_pair: dict[tuple[str, str], dict[str, object]] = {
            (str(row.get("stock") or "").strip(), str(row.get("future") or "").strip()): row
            for row in rows_list
        }
        candidate_payload: list[dict[str, object]] = []
        for candidate in candidates:
            pair_key = (candidate.stock, candidate.future)
            row = rows_by_pair.get(pair_key)
            signal_id_value: str | None = None
            if isinstance(row, dict):
                signal_id_value = _build_signal_id_from_row(row)
            candidate_payload.append(
                {
                    "signal_id": signal_id_value,
                    "stock": candidate.stock,
                    "future": candidate.future,
                    "direction": candidate.direction,
                    "last_execution_at": candidate.last_execution_at,
                    "age_sec": candidate.age_sec,
                    "open_leg_total": candidate.open_leg_total,
                    "open_stock_legs": candidate.open_stock_legs,
                    "open_future_legs": candidate.open_future_legs,
                    "reason_code": "LEG_IMBALANCE_TIMEOUT",
                }
            )

        if dry_run:
            return _finish(
                jsonify(
                    {
                        "status": "dry_run",
                        "policy": "auto_unwind_leg_imbalance_timeout",
                        "evaluated_at": now_utc.isoformat().replace("+00:00", "Z"),
                        "timeout_sec": timeout_sec,
                        "candidate_count": len(candidate_payload),
                        "candidates": candidate_payload,
                    }
                )
            )

        triggered: list[dict[str, object]] = []
        duplicates: list[dict[str, object]] = []
        blocked: list[dict[str, object]] = []
        errors: list[dict[str, object]] = []

        for candidate in candidates:
            action_payload: dict[str, object] = {
                "action": "exit",
                "stock": candidate.stock,
                "future": candidate.future,
                "direction": candidate.direction,
                "source": "system",
                "actor_id": actor_id,
                "reason_code": "LEG_IMBALANCE_TIMEOUT",
                "comment": f"auto_unwind_after_{candidate.age_sec}s",
                "status": "policy_submitted",
                "idempotency_key": (
                    f"auto-unwind:{candidate.stock}:{candidate.future}:{candidate.last_execution_at}"
                ),
            }
            result = _record_signal_action(
                signal_id=None,
                payload=action_payload,
                source_default="system",
                legacy_mode=False,
            )
            result_payload, result_status = _extract_response_payload(result)
            item = {
                "stock": candidate.stock,
                "future": candidate.future,
                "age_sec": candidate.age_sec,
                "last_execution_at": candidate.last_execution_at,
            }

            if isinstance(result_payload, dict):
                item["action_status"] = result_payload.get("status")
                item["action_id"] = result_payload.get("action_id")
                item["execution_event_id"] = result_payload.get("execution_event_id")
                item["reason_code"] = result_payload.get("reason_code")
                item["message"] = result_payload.get("message")
            else:
                item["action_status"] = "unknown"
                item["message"] = "non_json_response"

            if result_status >= 500:
                errors.append(item)
                continue
            action_status = str(item.get("action_status") or "").strip().lower()
            if action_status == "ok":
                triggered.append(item)
            elif action_status == "duplicate":
                duplicates.append(item)
            elif action_status == "blocked":
                blocked.append(item)
            else:
                errors.append(item)

        status = "ok" if not errors else "partial_error"
        return _finish(
            jsonify(
                {
                    "status": status,
                    "policy": "auto_unwind_leg_imbalance_timeout",
                    "evaluated_at": now_utc.isoformat().replace("+00:00", "Z"),
                    "timeout_sec": timeout_sec,
                    "candidate_count": len(candidate_payload),
                    "triggered_count": len(triggered),
                    "duplicate_count": len(duplicates),
                    "blocked_count": len(blocked),
                    "error_count": len(errors),
                    "candidates": candidate_payload,
                    "triggered": triggered,
                    "duplicates": duplicates,
                    "blocked": blocked,
                    "errors": errors,
                }
            )
        )

    @server.route("/api/v2/ops/health", methods=["GET"])
    def ops_health_v2_api():
        started_at = datetime.now(timezone.utc)
        checks: dict[str, dict[str, object]] = {}
        db_status = "ok"
        db_message: str | None = None
        try:
            with session_factory() as session:
                load_latest_signal_run(session)
        except Exception as exc:
            db_status = "error"
            db_message = str(exc)
            logger.exception("Ops health DB check failed")
        checks["database"] = {
            "status": db_status,
            "message": db_message,
        }
        checks["signal_refresh"] = {
            "status": str(refresh_state.get("status") or "unknown"),
            "enabled": bool(refresh_state.get("enabled")),
            "last_success_at": refresh_state.get("last_success_at"),
            "last_error": refresh_state.get("last_error"),
        }
        overall_status = "ok" if db_status == "ok" else "degraded"
        status_code = 200 if db_status == "ok" else 503
        result = (
            jsonify(
                {
                    "status": overall_status,
                    "timestamp": _iso_now(),
                    "checks": checks,
                }
            ),
            status_code,
        )
        return _observe_request("v2_ops_health", started_at, result)

    @server.route("/api/v2/ops/slo", methods=["GET"])
    def ops_slo_v2_api():
        started_at = datetime.now(timezone.utc)
        snapshot = observability.snapshot()
        endpoints = snapshot.get("endpoints")
        endpoint_stats = endpoints if isinstance(endpoints, dict) else {}
        actions_stats = (
            endpoint_stats.get("v2_signals_actions")
            if isinstance(endpoint_stats.get("v2_signals_actions"), dict)
            else {}
        )
        pretrade_stats = (
            endpoint_stats.get("v2_pretrade_check")
            if isinstance(endpoint_stats.get("v2_pretrade_check"), dict)
            else {}
        )
        auto_unwind_stats = (
            endpoint_stats.get("v2_auto_unwind_run")
            if isinstance(endpoint_stats.get("v2_auto_unwind_run"), dict)
            else {}
        )

        pretrade_failures_15m = observability.count_recent("pretrade_failure", window_sec=900)
        pretrade_degraded_15m = observability.count_recent("pretrade_degraded", window_sec=900)
        pretrade_errors_15m = observability.count_recent("pretrade_error", window_sec=900)
        execution_rejections_15m = observability.count_recent(
            "execution_rejected_fail_closed", window_sec=900
        )
        auto_unwind_triggered_15m = observability.count_recent("auto_unwind_triggered", window_sec=900)
        auto_unwind_errors_15m = observability.count_recent("auto_unwind_error", window_sec=900)

        alerts: list[dict[str, object]] = []
        pretrade_p95 = float(((pretrade_stats.get("latency_ms") or {}).get("p95") or 0.0))
        action_p95 = float(((actions_stats.get("latency_ms") or {}).get("p95") or 0.0))
        if pretrade_p95 > 1_500.0:
            alerts.append(
                {
                    "code": "PRETRADE_LATENCY_HIGH",
                    "severity": "warning",
                    "message": "Pretrade p95 latency exceeds 1500 ms.",
                    "value": pretrade_p95,
                }
            )
        if action_p95 > 800.0:
            alerts.append(
                {
                    "code": "ACTION_LATENCY_HIGH",
                    "severity": "warning",
                    "message": "Signal action p95 latency exceeds 800 ms.",
                    "value": action_p95,
                }
            )
        if execution_rejections_15m >= 5:
            alerts.append(
                {
                    "code": "EXECUTION_REJECTION_SPIKE",
                    "severity": "critical",
                    "message": "Fail-closed execution rejections in the last 15m reached threshold.",
                    "value": execution_rejections_15m,
                }
            )
        if pretrade_failures_15m >= 10:
            alerts.append(
                {
                    "code": "PRETRADE_FAILURE_SPIKE",
                    "severity": "warning",
                    "message": "Pretrade failures in the last 15m reached threshold.",
                    "value": pretrade_failures_15m,
                }
            )
        if auto_unwind_errors_15m >= 1:
            alerts.append(
                {
                    "code": "AUTO_UNWIND_ERRORS",
                    "severity": "critical",
                    "message": "Auto-unwind errors detected in the last 15m.",
                    "value": auto_unwind_errors_15m,
                }
            )

        result = jsonify(
            {
                "generated_at": snapshot.get("generated_at"),
                "slo_targets": {
                    "pretrade_p95_ms": 1500.0,
                    "signals_actions_p95_ms": 800.0,
                    "execution_rejections_15m": 5,
                    "pretrade_failures_15m": 10,
                    "auto_unwind_errors_15m": 1,
                },
                "api": {
                    "v2_signals_actions": actions_stats,
                    "v2_pretrade_check": pretrade_stats,
                    "v2_auto_unwind_run": auto_unwind_stats,
                },
                "events_15m": {
                    "pretrade_failures": pretrade_failures_15m,
                    "pretrade_degraded": pretrade_degraded_15m,
                    "pretrade_errors": pretrade_errors_15m,
                    "execution_rejections_fail_closed": execution_rejections_15m,
                    "auto_unwind_triggered": auto_unwind_triggered_15m,
                    "auto_unwind_errors": auto_unwind_errors_15m,
                },
                "signal_refresh_runtime": {
                    "status": refresh_state.get("status"),
                    "duration_ms": {
                        "p50": float(refresh_state.get("refresh_duration_ms_p50") or 0.0),
                        "p95": float(refresh_state.get("refresh_duration_ms_p95") or 0.0),
                    },
                    "ingest_lag_sec": refresh_state.get("ingest_lag_sec"),
                    "cache_hit_ratio": float(refresh_state.get("cache_hit_ratio") or 0.0),
                    "skip_reason": refresh_state.get("skip_reason"),
                    "fallback_full_replay_count": int(refresh_state.get("fallback_full_replay_count") or 0),
                },
                "alerts": alerts,
            }
        )
        return _observe_request("v2_ops_slo", started_at, result)

    @server.route("/api/v2/signals/history", methods=["GET"])
    @server.route("/api/signals/history", methods=["GET"])
    def signals_history_api():
        limit = int(request.args.get("limit", "500"))
        from_raw = request.args.get("from")
        to_raw = request.args.get("to")
        stock = request.args.get("stock")
        future = request.args.get("future")
        action = request.args.get("signal_action") or request.args.get("action")
        stock = stock.strip() if isinstance(stock, str) and stock.strip() else None
        future = future.strip() if isinstance(future, str) and future.strip() else None
        action = action.strip() if isinstance(action, str) and action.strip() else None
        from_ts = _parse_date_bound(from_raw, "start") if from_raw else None
        to_ts = _parse_date_bound(to_raw, "end") if to_raw else None
        if from_raw and from_ts is None:
            return jsonify({"error": "invalid_from"}), 400
        if to_raw and to_ts is None:
            return jsonify({"error": "invalid_to"}), 400
        with session_factory() as session:
            rows = load_signal_history(
                session,
                from_ts=from_ts,
                to_ts=to_ts,
                limit=limit,
                stock=stock,
                future=future,
                action=action,
            )
            payload = [
                _merge_signal_metrics(
                    {
                        "run_id": row.run_id,
                        "timestamp": row.timestamp.isoformat(),
                        "stock": row.stock_secid,
                        "future": row.future_secid,
                        "signal_action": row.action,
                        "signal_direction": row.direction,
                        "signal_score": row.score,
                        "signal_reasons": row.reasons,
                        "signal_metrics": row.metrics,
                    }
                )
                for row in rows
            ]
            return jsonify(payload)

    @server.route("/api/signals/execute", methods=["POST"])
    def signals_execute_api():
        payload = request.get_json(silent=True)
        if payload is None or not isinstance(payload, dict):
            return _bad_request("invalid_json")
        result = _record_signal_action(
            signal_id=None,
            payload=dict(payload),
            source_default="v1_adapter",
            legacy_mode=True,
        )
        response_payload, status_code = _extract_response_payload(result)
        if status_code >= 400:
            return result
        if not isinstance(response_payload, dict):
            return result
        return jsonify(
            {
                "status": response_payload.get("status", "ok"),
                "order_id": response_payload.get("order_id"),
            }
        )

    @server.route("/api/v2/signals/executions", methods=["GET"])
    @server.route("/api/signals/executions", methods=["GET"])
    def signals_executions_api():
        limit = int(request.args.get("limit", "200"))
        stock = request.args.get("stock")
        future = request.args.get("future")
        with session_factory() as session:
            rows = load_signal_executions(session, stock=stock, future=future, limit=limit)
            return jsonify(
                [
                    {
                        "timestamp": row.timestamp.isoformat(),
                        "stock": row.stock_secid,
                        "future": row.future_secid,
                        "direction": row.direction,
                        "action": _normalize_execution_action(row.action),
                        "price": row.price,
                        "quantity": row.quantity,
                        "side": row.side,
                        "order_id": row.order_id,
                        "status": row.status,
                        "note": row.note,
                    }
                    for row in rows
                ]
            )

    @server.route("/api/backtests", methods=["GET"])
    def backtests_api():
        df = pd.DataFrame()
        fresh = request.args.get("fresh", "").lower() in {"1", "true", "yes"}
        if settings.ui.use_unified_signal_engine:
            limit = int(request.args.get("limit", "500"))
            try:
                _, _, backtests = _load_latest_unified_output(
                    max_pairs=_resolved_unified_max_pairs(limit),
                    fresh=fresh,
                )
                df = backtests.copy()
            except Exception:
                logger.exception("Unified backtests failed")
                if not settings.ui.unified_allow_legacy_fallback:
                    return jsonify({"error": "server_error", "message": "unified_backtests_failed"}), 500
        if df.empty and settings.ui.unified_allow_legacy_fallback:
            df = load_backtest_summary(paths.data_dir)
        limit = int(request.args.get("limit", "500"))
        df = df.head(max(limit, 0)) if limit else df
        return jsonify(_df_to_records(df))

    @server.route("/api/v2/portfolio/rebalance/preview", methods=["GET"])
    def rebalance_preview_v2_api():
        limit = max(_parse_int(request.args.get("limit"), 12), 1)
        legacy = signals_active_api()
        rows, status_code = _extract_response_payload(legacy)
        if status_code >= 400:
            return legacy
        if not isinstance(rows, list):
            rows = []

        candidates: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            action = str(row.get("signal_action") or "").strip().lower()
            if action not in {"enter", "hold_open", "exit"}:
                continue
            score_raw = row.get("signal_score")
            try:
                score = float(score_raw) if score_raw is not None else 0.0
            except (TypeError, ValueError):
                score = 0.0
            candidates.append({**row, "_score": score})

        candidates.sort(key=lambda item: float(item.get("_score") or 0.0), reverse=True)
        selected = candidates[:limit]
        active_for_weight = [row for row in selected if str(row.get("signal_action")).lower() in {"enter", "hold_open"}]
        equal_weight = 1.0 / len(active_for_weight) if active_for_weight else 0.0

        positions: list[dict[str, object]] = []
        for row in selected:
            signal_action = str(row.get("signal_action") or "").strip().lower()
            lifecycle_state = _derive_lifecycle_state(row)
            target_weight = equal_weight if signal_action in {"enter", "hold_open"} else 0.0
            positions.append(
                {
                    "entity_ref": _build_pair_entity_ref(row.get("stock"), row.get("future")),
                    "target_weight": target_weight,
                    "signal_id": _build_signal_id_from_row(row),
                    "lifecycle_state": lifecycle_state,
                    "signal_action": signal_action,
                    "signal_score": row.get("signal_score"),
                    "reasons": row.get("signal_reasons") or [],
                }
            )

        plan_id = f"rebal-{uuid.uuid4().hex[:12]}"
        max_positions = int(settings.risk_profile.max_positions or 0)
        risk_checks = [
            {
                "check": "max_positions",
                "passed": len(active_for_weight) <= max_positions if max_positions > 0 else True,
                "limit": max_positions if max_positions > 0 else None,
                "value": len(active_for_weight),
            }
        ]
        return jsonify(
            {
                "rebalance_plan_id": plan_id,
                "generated_at": _iso_now(),
                "positions": positions,
                "summary": {
                    "selected": len(selected),
                    "target_active_positions": len(active_for_weight),
                    "equal_weight": equal_weight,
                },
                "risk_checks": risk_checks,
            }
        )

    @server.route("/api/v2/portfolio/rebalance/commit", methods=["POST"])
    def rebalance_commit_v2_api():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _bad_request("invalid_json")
        plan_id = str(payload.get("rebalance_plan_id") or "").strip()
        if not plan_id:
            return _bad_request("rebalance_plan_id is required")
        positions = payload.get("positions")
        if not isinstance(positions, list):
            return _bad_request("positions must be a list")
        actor_id = str(payload.get("actor_id") or "operator").strip() or "operator"
        commit_id = f"rebal-commit-{uuid.uuid4().hex[:12]}"
        entry = {
            "commit_id": commit_id,
            "rebalance_plan_id": plan_id,
            "actor_id": actor_id,
            "positions": positions,
            "committed_at": _iso_now(),
            "note": payload.get("note"),
        }
        commits_path = paths.data_dir / "portfolio" / "rebalance_commits.jsonl"
        _append_jsonl(commits_path, entry)
        return jsonify(
            {
                "status": "ok",
                "commit_id": commit_id,
                "rebalance_plan_id": plan_id,
                "positions_committed": len(positions),
                "committed_at": entry["committed_at"],
            }
        )

    @server.route("/api/spread-series", methods=["GET"])
    def spread_series_api():
        stock = request.args.get("stock")
        future = request.args.get("future")
        if not stock or not future:
            return jsonify({"error": "missing_params"}), 400
        full_life = request.args.get("full_life", "").lower() in {"1", "true", "yes"}
        window_raw = request.args.get("window_days", "60")
        try:
            window_days = max(int(window_raw), 1)
        except ValueError:
            return jsonify({"error": "invalid_window"}), 400
        window_days = min(window_days, 3650)

        cache_dir = paths.data_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_suffix = "full" if full_life else str(window_days)
        cache_path = cache_dir / f"spread_{stock}_{future}_{cache_suffix}_{_CACHE_VERSION}.json"
        cached = _read_cache(cache_path, ttl_minutes=60)
        if cached is not None:
            return jsonify(cached)

        series_df = pd.DataFrame()
        if settings.ui.use_unified_signal_engine:
            try:
                series_df = build_unified_spread_series(
                    settings,
                    paths.data_dir,
                    stock=stock,
                    future=future,
                    window_days=window_days,
                    full_life=full_life,
                    ttl_sec=_unified_ttl_sec(),
                )
            except Exception:
                logger.exception("Unified spread-series failed")
                if not settings.ui.unified_allow_legacy_fallback:
                    return jsonify({"error": "server_error", "message": "unified_spread_series_failed"}), 500
        if series_df.empty and settings.ui.unified_allow_legacy_fallback:
            series_df = build_spread_series(
                settings, stock, future, window_days=window_days, full_life=full_life
            )
        if series_df.empty:
            return jsonify([])
        series_df = _stringify_datetime_columns(series_df)
        records = _df_to_records(series_df)
        _write_cache(cache_path, records)
        return jsonify(records)

    def _run_pretrade_check(payload: dict[str, object]):
        stock = str(payload.get("stock") or "").strip()
        future = str(payload.get("future") or "").strip()
        if not stock or not future:
            return jsonify({"error": "missing_params", "message": "stock and future are required"}), 400

        top_pairs = load_top_pairs(paths.data_dir)
        pair_row = pd.DataFrame()
        if not top_pairs.empty and {"stock", "future"}.issubset(top_pairs.columns):
            pair_row = top_pairs[
                (top_pairs["stock"].astype(str) == stock)
                & (top_pairs["future"].astype(str) == future)
            ]

        row = pair_row.iloc[0] if not pair_row.empty else None
        default_direction = "cash_and_carry"
        if row is not None and "signal_direction" in row and pd.notna(row.get("signal_direction")):
            default_direction = str(row.get("signal_direction"))
        normalized_default_direction = normalize_pretrade_direction(
            default_direction, default="cash_and_carry"
        )
        if normalized_default_direction is None:
            normalized_default_direction = "cash_and_carry"
        direction = normalize_pretrade_direction(
            payload.get("direction"), default=normalized_default_direction
        )
        if direction is None:
            return _bad_request("direction must be cash_and_carry or reverse")

        spot_default = None
        fut_default = None
        spread_default = None
        if row is not None:
            spot_default = row.get("spot")
            fut_default = row.get("future_price")
            spread_default = row.get("spread_mid")

        spot_target = _parse_float(
            payload.get("spot_target"),
            float(spot_default) if pd.notna(spot_default) else float("nan"),
        )
        future_target = _parse_float(
            payload.get("future_target"),
            float(fut_default) if pd.notna(fut_default) else float("nan"),
        )
        if math.isnan(spot_target) or math.isnan(future_target):
            return _bad_request("spot_target and future_target are required if pair is absent in top_pairs")

        spread_fallback = spot_target - future_target
        spread_target = _parse_float(
            payload.get("spread_target"),
            float(spread_default) if pd.notna(spread_default) else spread_fallback,
        )

        snapshots = max(_parse_int(payload.get("snapshots"), 4), 1)
        snapshots = min(snapshots, 12)
        min_hits = max(_parse_int(payload.get("min_hits"), 2), 1)
        min_hits = min(min_hits, snapshots)
        alpha_cfg = settings.spread_carry_alpha
        eps_default = float(
            getattr(alpha_cfg, "entry_price_tolerance_pct", 0.0015) or 0.0015
        )
        stock_eps_default = float(
            getattr(alpha_cfg, "entry_stock_tolerance_pct", None) or eps_default
        )
        future_eps_default = float(
            getattr(alpha_cfg, "entry_future_tolerance_pct", None) or eps_default
        )
        spread_eps_default = float(
            getattr(alpha_cfg, "entry_spread_tolerance_pct", None) or eps_default
        )
        eps = max(_parse_float(payload.get("eps"), eps_default), 0.0001)
        eps = min(eps, 0.05)
        stock_eps = max(_parse_float(payload.get("stock_eps"), stock_eps_default), 0.0001)
        stock_eps = min(stock_eps, 0.05)
        future_eps = max(_parse_float(payload.get("future_eps"), future_eps_default), 0.0001)
        future_eps = min(future_eps, 0.05)
        spread_eps = max(_parse_float(payload.get("spread_eps"), spread_eps_default), 0.0001)
        spread_eps = min(spread_eps, 0.05)
        sync_sec = max(_parse_float(payload.get("sync_sec"), 120.0), 1.0)
        poll_sec = max(_parse_float(payload.get("poll_sec"), 5.0), 0.0)
        poll_sec = min(poll_sec, 15.0)

        qty_fut_default = float(settings.spread_carry_alpha.max_contracts_per_pair or 1)
        qty_fut = max(_parse_float(payload.get("qty_fut"), qty_fut_default), 0.0)
        participation_default = float(settings.spread_carry_alpha.participation_rate or 0.1)
        participation_rate = max(
            _parse_float(payload.get("participation_rate"), participation_default),
            0.000001,
        )
        participation_rate = min(participation_rate, 1.0)

        future_scale = _future_scale_from_raw(paths.data_dir / "raw" / "futures.csv", future)
        client = MoexIssClient(
            settings.moex.base_url,
            settings.moex.request_timeout_sec,
            max_retries=settings.moex.request_max_retries,
            retry_backoff_sec=settings.moex.request_retry_backoff_sec,
            retry_max_backoff_sec=settings.moex.request_retry_max_backoff_sec,
            fallback_ips=settings.moex.fallback_ips,
            force_fallback=settings.moex.force_fallback,
        )

        try:
            result = run_delay_gate(
                client,
                stock=stock,
                future=future,
                direction=direction,
                spot_target=spot_target,
                future_target=future_target,
                spread_target=spread_target,
                future_scale=future_scale,
                qty_fut=qty_fut,
                participation_rate=participation_rate,
                snapshots=snapshots,
                min_hits=min_hits,
                eps=eps,
                stock_eps=stock_eps,
                future_eps=future_eps,
                spread_eps=spread_eps,
                sync_sec=sync_sec,
                poll_sec=poll_sec,
                stock_engine=settings.moex.engine_shares,
                stock_market=settings.moex.market_shares,
                stock_board=settings.moex.shares_board,
                fut_engine=settings.moex.engine_futures,
                fut_market=settings.moex.market_futures,
                fut_board=settings.moex.futures_board,
            )
        except Exception as exc:
            if settings.ui.pretrade_fail_open_on_transport_error and _is_iss_transport_error(exc):
                logger.warning(
                    "Pretrade delay gate transport failure; returning fail-open response",
                    exc_info=True,
                )
                result = _build_pretrade_fail_open_result(
                    stock=stock,
                    future=future,
                    direction=direction,
                    spot_target=spot_target,
                    future_target=future_target,
                    spread_target=spread_target,
                    eps=eps,
                    stock_eps=stock_eps,
                    future_eps=future_eps,
                    spread_eps=spread_eps,
                    future_scale=future_scale,
                    qty_fut=qty_fut,
                    participation_rate=participation_rate,
                    min_hits=min_hits,
                    error_text=str(exc),
                )
            else:
                logger.exception("Pretrade delay gate failed")
                return jsonify({"error": "server_error", "message": str(exc)}), 500

        runtime_params = PretradeRuntimeParams(
            snapshots=snapshots,
            min_hits=min_hits,
            eps=eps,
            sync_sec=sync_sec,
            poll_sec=poll_sec,
            qty_fut=qty_fut,
            participation_rate=participation_rate,
            future_scale=future_scale,
        )
        enriched = enrich_pretrade_result(result, params=runtime_params)
        params = enriched.get("params")
        if isinstance(params, dict):
            params["stock_eps"] = stock_eps
            params["future_eps"] = future_eps
            params["spread_eps"] = spread_eps
        return jsonify(_sanitize_value(enriched))

    @server.route("/api/pretrade/check", methods=["GET"])
    def pretrade_check_api():
        return _run_pretrade_check(dict(request.args.to_dict(flat=True)))

    @server.route("/api/v2/pretrade/check", methods=["POST"])
    def pretrade_check_v2_api():
        started_at = datetime.now(timezone.utc)
        payload = request.get_json(silent=True)
        if payload is None:
            return _observe_request("v2_pretrade_check", started_at, _bad_request("invalid_json"))
        if not isinstance(payload, dict):
            return _observe_request(
                "v2_pretrade_check", started_at, _bad_request("payload must be object")
            )
        result = _run_pretrade_check(dict(payload))
        _mark_pretrade_events(result)
        return _observe_request("v2_pretrade_check", started_at, result)

    app = Dash(__name__, server=server, url_base_pathname="/dash/")
    app.layout = html.Div(
        [
            html.H2("MOEX Carry Dashboard"),
            dcc.Interval(id="refresh", interval=60_000, n_intervals=0),
            dcc.Tabs(
                [
                    dcc.Tab(
                        label="Top pairs",
                        children=[
                            dash_table.DataTable(
                                id="top_pairs_table",
                                data=[],
                                columns=[],
                                page_size=15,
                                **BASE_TABLE_STYLE,
                            )
                        ],
                    ),
                    dcc.Tab(
                        label="Signals",
                        children=[
                            dash_table.DataTable(
                                id="signals_table",
                                data=[],
                                columns=[],
                                page_size=15,
                                **BASE_TABLE_STYLE,
                            )
                        ],
                    ),
                    dcc.Tab(
                        label="Backtests",
                        children=[
                            dash_table.DataTable(
                                id="backtest_table",
                                data=[],
                                columns=[],
                                page_size=10,
                                **BASE_TABLE_STYLE,
                            )
                        ],
                    ),
                    dcc.Tab(
                        label="Decisions",
                        children=[
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Label("Strategy"),
                                            dcc.Dropdown(id="decision_filter_strategy", clearable=True),
                                        ],
                                        style={"width": "20%", "display": "inline-block"},
                                    ),
                                    html.Div(
                                        [
                                            html.Label("Instrument"),
                                            dcc.Dropdown(id="decision_filter_instrument", clearable=True),
                                        ],
                                        style={"width": "20%", "display": "inline-block", "marginLeft": "10px"},
                                    ),
                                    html.Div(
                                        [
                                            html.Label("Risk state"),
                                            dcc.Dropdown(id="decision_filter_risk", clearable=True),
                                        ],
                                        style={"width": "20%", "display": "inline-block", "marginLeft": "10px"},
                                    ),
                                    html.Div(
                                        [
                                            html.Label("News severity"),
                                            dcc.Dropdown(id="decision_filter_news", clearable=True),
                                        ],
                                        style={"width": "20%", "display": "inline-block", "marginLeft": "10px"},
                                    ),
                                ],
                                style={"marginBottom": "12px"},
                            ),
                            dash_table.DataTable(
                                id="decision_table",
                                data=[],
                                columns=_decision_columns(),
                                page_size=12,
                                row_selectable="single",
                                filter_action="native",
                                sort_action="native",
                                style_data_conditional=DECISION_STYLE,
                                **BASE_TABLE_STYLE,
                            ),
                            html.H4("Decision details"),
                            html.Pre(
                                id="decision_detail",
                                style={
                                    "whiteSpace": "pre-wrap",
                                    "backgroundColor": "#f9fafb",
                                    "border": "1px solid #e5e7eb",
                                    "padding": "8px",
                                    "fontFamily": "Consolas, monospace",
                                    "fontSize": "12px",
                                },
                            ),
                        ],
                    ),
                ]
            ),
        ]
    )

    @app.callback(
        Output("top_pairs_table", "data"),
        Output("top_pairs_table", "columns"),
        Output("signals_table", "data"),
        Output("signals_table", "columns"),
        Output("backtest_table", "data"),
        Output("backtest_table", "columns"),
        Input("refresh", "n_intervals"),
    )
    def _refresh(_):
        if settings.ui.use_unified_signal_engine:
            try:
                top_pairs, signals, backtest = _load_latest_unified_output(
                    max_pairs=_resolved_unified_max_pairs(settings.ui.signal_refresh_max_pairs),
                    fresh=False,
                )
                top_pairs = _apply_score_gate_filter(
                    top_pairs.copy(),
                    require_score_gate=_default_require_score_gate_for_top_pairs(settings),
                )
                signals = _apply_score_gate_filter(
                    signals.copy(),
                    require_score_gate=_default_require_score_gate_for_signals(settings),
                )
                backtest = backtest.copy()
            except Exception:
                logger.exception("Unified Dash refresh failed")
                top_pairs = pd.DataFrame()
                signals = pd.DataFrame()
                backtest = pd.DataFrame()
            if settings.ui.unified_allow_legacy_fallback:
                if top_pairs.empty:
                    top_pairs = load_top_pairs(paths.data_dir)
                if signals.empty:
                    signals = load_signals(paths.data_dir)
                if backtest.empty:
                    backtest = load_backtest_summary(paths.data_dir)
        else:
            top_pairs = load_top_pairs(paths.data_dir)
            signals = load_signals(paths.data_dir)
            backtest = load_backtest_summary(paths.data_dir)
        return (
            top_pairs.to_dict("records"),
            _table_columns(top_pairs),
            signals.to_dict("records"),
            _table_columns(signals),
            backtest.to_dict("records"),
            _table_columns(backtest),
        )

    @app.callback(
        Output("decision_table", "data"),
        Output("decision_table", "columns"),
        Output("decision_filter_strategy", "options"),
        Output("decision_filter_instrument", "options"),
        Output("decision_filter_risk", "options"),
        Output("decision_filter_news", "options"),
        Input("refresh", "n_intervals"),
        Input("decision_filter_strategy", "value"),
        Input("decision_filter_instrument", "value"),
        Input("decision_filter_risk", "value"),
        Input("decision_filter_news", "value"),
    )
    def _refresh_decisions(_, strategy_value, instrument_value, risk_value, news_value):
        decisions = load_decision_view(paths.data_dir)
        if decisions.empty:
            return [], _decision_columns(), [], [], [], []
        decisions = _prepare_decisions(decisions)
        filters = {
            "strategy_type": strategy_value,
            "primary_instrument": instrument_value,
            "risk_state": risk_value,
            "news_severity": news_value,
        }
        filtered = decisions
        for column, value in filters.items():
            if value:
                filtered = filtered[filtered[column] == value]
        strategy_options = [{"label": value, "value": value} for value in sorted(decisions["strategy_type"].unique())]
        instrument_options = [
            {"label": value, "value": value}
            for value in sorted(decisions["primary_instrument"].fillna("").unique())
            if value
        ]
        risk_options = [{"label": value, "value": value} for value in sorted(decisions["risk_state"].unique())]
        news_options = [{"label": value, "value": value} for value in sorted(decisions["news_severity"].unique())]
        return (
            filtered.to_dict("records"),
            _decision_columns(),
            strategy_options,
            instrument_options,
            risk_options,
            news_options,
        )

    @app.callback(
        Output("decision_detail", "children"),
        Input("decision_table", "selected_rows"),
        State("decision_table", "data"),
    )
    def _show_decision_detail(selected_rows, rows):
        if not selected_rows or not rows:
            return "Select a decision row to inspect the full decision_log."
        row = rows[selected_rows[0]]
        decision_id = row.get("decision_id")
        logs = load_decision_log(paths.data_dir)
        if logs.empty or not decision_id:
            return "Decision log entry not found."
        match = logs[logs["decision_id"] == decision_id]
        if match.empty:
            return "Decision log entry not found."
        entry = match.iloc[0].to_dict()
        return json.dumps(entry, ensure_ascii=False, indent=2)

    return app


def run_ui(settings: AppSettings) -> None:
    app = create_app(settings)
    app.run(host=settings.ui.host, port=settings.ui.port, debug=False)
