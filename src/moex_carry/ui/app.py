from __future__ import annotations

import json
import logging
import math
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
from moex_carry.forward.runtime import load_forward_status, start_forward_run
from moex_carry.hpo.runtime import load_hpo_status, start_hpo_run
from moex_carry.parameter_specs import get_parameter_specs
from moex_carry.pipeline import build_spread_series, run_signal_cycle
from moex_carry.pretrade.delay_gate import run_delay_gate
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
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
    if raw in {"enter", "open", "hold_open", "hold"}:
        # hold_open in execution logs is treated as opening/maintaining leg exposure.
        return "enter"
    return raw or "enter"


def _normalize_order_id(value: object) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    return raw or None


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

    refresh_enabled = bool(settings.ui.signal_refresh_enabled)
    refresh_interval = int(settings.ui.signal_refresh_interval_sec or 0)
    refresh_daily_time = _parse_daily_time(settings.ui.signal_refresh_daily_time)
    refresh_tz = _resolve_tz(settings.ui.signal_refresh_timezone, settings.environment.timezone)
    refresh_mode = "daily" if refresh_daily_time else "interval"
    refresh_state = {
        "enabled": refresh_enabled,
        "interval_sec": refresh_interval,
        "mode": refresh_mode,
        "daily_time": settings.ui.signal_refresh_daily_time,
        "timezone": settings.ui.signal_refresh_timezone or settings.environment.timezone,
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

    def _unified_snapshot(max_pairs: int | None, *, force: bool = False) -> UnifiedMarketSnapshot:
        return build_unified_market_snapshot(
            settings,
            paths.data_dir,
            force=force,
            ttl_sec=_unified_ttl_sec(),
            max_pairs=max_pairs,
        )

    def _persist_unified_signal_run(max_pairs: int | None) -> int:
        snapshot = _unified_snapshot(max_pairs=max_pairs, force=True)
        if settings.ui.signal_refresh_save_csv:
            persist_snapshot_to_csv(snapshot, paths.data_dir)
        run_id = f"signal-run-{uuid.uuid4().hex[:8]}"
        as_of = datetime.now(timezone.utc)
        params = {
            "max_pairs": max_pairs,
            "engine": "unified_minute_replay",
            "warnings": list(snapshot.warnings),
            "errors": list(snapshot.errors),
        }
        records = snapshot.signals.to_dict("records") if not snapshot.signals.empty else []
        with session_factory() as session:
            store_signal_run(session, run_id, as_of, params)
            if records:
                store_signal_history(session, run_id, as_of, records)
        return len(records)

    def _run_signal_refresh(trigger: str, force: bool = False) -> bool:
        if not refresh_enabled and not force:
            refresh_state["status"] = "disabled"
            refresh_state["last_error"] = f"skip:{trigger}"
            return False
        if refresh_lock.locked():
            refresh_state["status"] = "busy"
            refresh_state["last_error"] = f"skip:{trigger}"
            return False
        with refresh_lock:
            refresh_state["status"] = "running"
            refresh_state["last_started_at"] = _iso_now()
            refresh_state["last_error"] = None
            try:
                if settings.ui.use_unified_signal_engine:
                    rows = _persist_unified_signal_run(
                        _resolved_unified_max_pairs(settings.ui.signal_refresh_max_pairs)
                    )
                    refresh_state["rows"] = int(rows)
                    refresh_state["engine"] = "unified_minute_replay"
                else:
                    run_signal_cycle(
                        settings,
                        max_pairs=settings.ui.signal_refresh_max_pairs,
                        save_csv=settings.ui.signal_refresh_save_csv,
                    )
                    refresh_state["engine"] = "legacy_pipeline"
                refresh_state["last_success_at"] = _iso_now()
                refresh_state["status"] = "ok"
            except Exception as exc:
                refresh_state["last_error"] = str(exc)
                refresh_state["status"] = "error"
                logger.exception("Signal refresh failed")
                return False
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
        return response

    @server.route("/api/signals/refresh-status", methods=["GET"])
    def signals_refresh_status_api():
        return jsonify(refresh_state)

    @server.route("/api/signals/refresh", methods=["POST"])
    def signals_refresh_api():
        if refresh_lock.locked():
            return jsonify({**refresh_state, "status": "busy"}), 409
        ok = _run_signal_refresh("manual", force=True)
        status_code = 200 if ok else 500
        return jsonify(refresh_state), status_code

    @server.route("/api/decision-view", methods=["GET"])
    def decision_view_api():
        view_path = paths.data_dir / "decisions" / "decision_view.jsonl"
        records = load_jsonl(view_path)
        df = pd.DataFrame(records)
        df = _apply_query_filters(df, request.args)
        df = df.sort_values("created_at", ascending=False) if not df.empty else df
        limit = int(request.args.get("limit", "500"))
        df = df.head(max(limit, 0)) if limit else df
        response_rows = _df_to_records(df)
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
                    "action": action.get("action"),
                    "status": action.get("status"),
                    "actor": action.get("actor"),
                    "note": action.get("note"),
                    "created_at": action.get("created_at"),
                }
            execution = latest_executions.get(decision_id)
            if isinstance(execution, dict):
                row["execution_status"] = {
                    "status": execution.get("status"),
                    "requested_at": execution.get("requested_at"),
                    "executed_at": execution.get("executed_at"),
                }
        return jsonify(response_rows)

    @server.route("/api/decision-log/<decision_id>", methods=["GET"])
    def decision_log_api(decision_id: str):
        log_path = paths.data_dir / "decisions" / "decision_log.jsonl"
        records = load_jsonl(log_path)
        for record in records:
            if record.get("decision_id") == decision_id:
                return jsonify(record)
        return jsonify({"error": "not_found"}), 404

    @server.route("/api/decisions/<decision_id>/action", methods=["GET", "POST"])
    def decision_action_api(decision_id: str):
        decisions_dir = paths.data_dir / "decisions"
        log_path = decisions_dir / "decision_log.jsonl"
        view_path = decisions_dir / "decision_view.jsonl"
        records = load_jsonl(log_path)
        if not any(record.get("decision_id") == decision_id for record in records):
            view_records = load_jsonl(view_path)
            if not any(record.get("decision_id") == decision_id for record in view_records):
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
        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action", "")).lower().strip()
        if action not in {"approve", "reject"}:
            return jsonify({"error": "invalid_action"}), 400
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        action_entry = {
            "decision_id": decision_id,
            "action": action,
            "status": "recorded",
            "actor": payload.get("actor") or "operator",
            "note": payload.get("note"),
            "created_at": created_at,
        }
        _append_jsonl(actions_path, action_entry)
        request_id = payload.get("request_id") or f"exec-{uuid.uuid4().hex}"
        execution_entry = {
            "decision_id": decision_id,
            "request_id": request_id,
            "action": action,
            "status": "queued",
            "requested_at": created_at,
        }
        _append_jsonl(executions_path, execution_entry)
        return jsonify(
            {
                "status": "ok",
                "decision_id": decision_id,
                "operator_action": action_entry,
                "execution_status": execution_entry,
            }
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
        request_payload = payload
        if isinstance(payload, dict):
            if "request" in payload:
                request_payload = payload.get("request")
                precompute = _parse_bool(payload.get("precompute"))
            elif "precompute" in payload:
                precompute = _parse_bool(payload.get("precompute"))
                request_payload = dict(payload)
                request_payload.pop("precompute", None)
        if not isinstance(request_payload, dict):
            return _bad_request("missing_request")
        try:
            backtest_request = BacktestRequest.model_validate(request_payload)
        except ValidationError as exc:
            return _bad_request("validation_error", details=exc.errors())
        try:
            report = run_backtest_v2_cached(backtest_request, paths.data_dir, precompute=precompute)
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

    @server.route("/api/top-pairs", methods=["GET"])
    def top_pairs_api():
        all_pairs = request.args.get("all", "").lower() in {"1", "true", "yes"}
        limit = int(request.args.get("limit", "500"))
        df = pd.DataFrame()
        if settings.ui.use_unified_signal_engine:
            try:
                max_pairs = None if all_pairs else _resolved_unified_max_pairs(limit)
                snapshot = _unified_snapshot(max_pairs=max_pairs, force=False)
                df = snapshot.top_pairs.copy()
            except Exception:
                logger.exception("Unified top-pairs failed")
                if not settings.ui.unified_allow_legacy_fallback:
                    return jsonify({"error": "server_error", "message": "unified_top_pairs_failed"}), 500
        if df.empty and settings.ui.unified_allow_legacy_fallback:
            df = load_top_pairs(paths.data_dir)
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
        return jsonify(records)

    @server.route("/api/signals", methods=["GET"])
    def signals_api():
        df = pd.DataFrame()
        if settings.ui.use_unified_signal_engine:
            limit = int(request.args.get("limit", "500"))
            try:
                snapshot = _unified_snapshot(max_pairs=_resolved_unified_max_pairs(limit), force=False)
                df = snapshot.signals.copy()
            except Exception:
                logger.exception("Unified signals failed")
                if not settings.ui.unified_allow_legacy_fallback:
                    return jsonify({"error": "server_error", "message": "unified_signals_failed"}), 500
        if df.empty and settings.ui.unified_allow_legacy_fallback:
            df = load_signals(paths.data_dir)
        limit = int(request.args.get("limit", "500"))
        df = df.head(max(limit, 0)) if limit else df
        records = [_merge_signal_metrics(record) for record in _df_to_records(df)]
        return jsonify(records)

    @server.route("/api/signals/active", methods=["GET"])
    def signals_active_api():
        with session_factory() as session:
            latest = load_latest_signal_run(session)
            if not latest:
                return jsonify([])
            rows = load_active_signals(session, latest.run_id)
            executions = load_open_executions(session)
            position_state: dict[tuple[str, str], dict[str, object]] = {}
            for exec_row in sorted(executions, key=lambda item: item.timestamp):
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
                if action not in {"enter", "exit"}:
                    continue
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
                state["last_execution_at"] = exec_row.timestamp
                if exec_row.direction is not None:
                    state["direction"] = exec_row.direction

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
                }
                actionable.append(_merge_signal_metrics(payload))

            actionable.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
            actionable.sort(key=lambda item: 0 if bool(item.get("position_open")) else 1)
            return jsonify(actionable)

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
        payload = request.get_json(silent=True) or {}
        normalized_action = _normalize_execution_action(payload.get("action"))
        payload["action"] = normalized_action
        order_id = _normalize_order_id(payload.get("order_id"))
        if order_id is None:
            side = _normalize_execution_leg(payload.get("side"))
            stock = str(payload.get("stock") or "").strip()
            future = str(payload.get("future") or "").strip()
            if side in {"stock", "future"} and stock and future:
                order_id = f"{stock}-{future}-{normalized_action}-{uuid.uuid4().hex[:10]}"
        payload["order_id"] = order_id
        payload["timestamp"] = datetime.now(timezone.utc)
        with session_factory() as session:
            store_signal_execution(session, payload["timestamp"], payload)
        return jsonify({"status": "ok", "order_id": order_id})

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
        if settings.ui.use_unified_signal_engine:
            limit = int(request.args.get("limit", "500"))
            try:
                snapshot = _unified_snapshot(max_pairs=_resolved_unified_max_pairs(limit), force=False)
                df = snapshot.backtests.copy()
            except Exception:
                logger.exception("Unified backtests failed")
                if not settings.ui.unified_allow_legacy_fallback:
                    return jsonify({"error": "server_error", "message": "unified_backtests_failed"}), 500
        if df.empty and settings.ui.unified_allow_legacy_fallback:
            df = load_backtest_summary(paths.data_dir)
        limit = int(request.args.get("limit", "500"))
        df = df.head(max(limit, 0)) if limit else df
        return jsonify(_df_to_records(df))

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

    @server.route("/api/pretrade/check", methods=["GET"])
    def pretrade_check_api():
        stock = request.args.get("stock")
        future = request.args.get("future")
        if not stock or not future:
            return jsonify({"error": "missing_params", "message": "stock and future are required"}), 400

        top_pairs = load_top_pairs(paths.data_dir)
        pair_row = pd.DataFrame()
        if not top_pairs.empty and {"stock", "future"}.issubset(top_pairs.columns):
            pair_row = top_pairs[
                (top_pairs["stock"].astype(str) == str(stock))
                & (top_pairs["future"].astype(str) == str(future))
            ]

        row = pair_row.iloc[0] if not pair_row.empty else None
        default_direction = "cash_and_carry"
        if row is not None and "signal_direction" in row and pd.notna(row.get("signal_direction")):
            default_direction = str(row.get("signal_direction"))
        direction = str(request.args.get("direction") or default_direction).strip().lower()
        if direction not in {"cash_and_carry", "reverse"}:
            return _bad_request("direction must be cash_and_carry or reverse")

        spot_default = None
        fut_default = None
        spread_default = None
        if row is not None:
            spot_default = row.get("spot")
            fut_default = row.get("future_price")
            spread_default = row.get("spread_mid")

        spot_target = _parse_float(request.args.get("spot_target"), float(spot_default) if pd.notna(spot_default) else float("nan"))
        future_target = _parse_float(
            request.args.get("future_target"),
            float(fut_default) if pd.notna(fut_default) else float("nan"),
        )
        if math.isnan(spot_target) or math.isnan(future_target):
            return _bad_request("spot_target and future_target are required if pair is absent in top_pairs")

        spread_fallback = spot_target - future_target
        spread_target = _parse_float(
            request.args.get("spread_target"),
            float(spread_default) if pd.notna(spread_default) else spread_fallback,
        )

        snapshots = max(_parse_int(request.args.get("snapshots"), 4), 1)
        snapshots = min(snapshots, 12)
        min_hits = max(_parse_int(request.args.get("min_hits"), 2), 1)
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
        eps = max(_parse_float(request.args.get("eps"), eps_default), 0.0001)
        eps = min(eps, 0.05)
        stock_eps = max(_parse_float(request.args.get("stock_eps"), stock_eps_default), 0.0001)
        stock_eps = min(stock_eps, 0.05)
        future_eps = max(_parse_float(request.args.get("future_eps"), future_eps_default), 0.0001)
        future_eps = min(future_eps, 0.05)
        spread_eps = max(_parse_float(request.args.get("spread_eps"), spread_eps_default), 0.0001)
        spread_eps = min(spread_eps, 0.05)
        sync_sec = max(_parse_float(request.args.get("sync_sec"), 120.0), 1.0)
        poll_sec = max(_parse_float(request.args.get("poll_sec"), 5.0), 0.0)
        poll_sec = min(poll_sec, 15.0)

        qty_fut_default = float(settings.spread_carry_alpha.max_contracts_per_pair or 1)
        qty_fut = max(_parse_float(request.args.get("qty_fut"), qty_fut_default), 0.0)
        participation_default = float(settings.spread_carry_alpha.participation_rate or 0.1)
        participation_rate = max(
            _parse_float(request.args.get("participation_rate"), participation_default),
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

        result["params"] = {
            "snapshots": snapshots,
            "min_hits": min_hits,
            "eps": eps,
            "stock_eps": stock_eps,
            "future_eps": future_eps,
            "spread_eps": spread_eps,
            "sync_sec": sync_sec,
            "poll_sec": poll_sec,
            "qty_fut": qty_fut,
            "participation_rate": participation_rate,
            "future_scale": future_scale,
        }
        return jsonify(_sanitize_value(result))

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
                snapshot = _unified_snapshot(
                    max_pairs=_resolved_unified_max_pairs(settings.ui.signal_refresh_max_pairs),
                    force=False,
                )
                top_pairs = snapshot.top_pairs.copy()
                signals = snapshot.signals.copy()
                backtest = snapshot.backtests.copy()
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
