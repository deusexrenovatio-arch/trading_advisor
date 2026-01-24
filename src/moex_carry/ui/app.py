from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
from dash import Dash, Input, Output, State, dash_table, dcc, html
from dash.dash_table.Format import Format, Scheme, Trim
from flask import Flask, jsonify, request

from moex_carry.config import AppSettings, resolve_paths
from moex_carry.decision_log import load_jsonl
from moex_carry.pipeline import build_spread_series
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_active_signals,
    load_latest_signal_run,
    load_open_executions,
    load_signal_executions,
    load_signal_history,
    store_signal_execution,
)
from moex_carry.ui.data import (
    load_backtest_summary,
    load_decision_log,
    load_decision_view,
    load_signals,
    load_top_pairs,
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


_CACHE_VERSION = "v2"


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


def _df_to_records(df: pd.DataFrame) -> list[dict[str, object]]:
    if df.empty:
        return []
    cleaned = df.astype(object).where(pd.notna(df), None)
    records = cleaned.to_dict("records")
    return [_sanitize_value(record) for record in records]


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


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

    @server.after_request
    def _cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

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

    @server.route("/api/top-pairs", methods=["GET"])
    def top_pairs_api():
        df = load_top_pairs(paths.data_dir)
        if not df.empty and "signal_score_norm" not in df.columns:
            if {"zscore", "implied_rate_net", "required_rate"}.issubset(df.columns):
                z_entry = settings.strategy.z_entry
                implied_buffer = settings.strategy.implied_rate_buffer
                z_component = df["zscore"].abs() / z_entry if z_entry else 0.0
                rate_gap = (df["implied_rate_net"] - df["required_rate"]).abs()
                rate_component = rate_gap / implied_buffer if implied_buffer else 0.0
                df["signal_score_norm"] = 0.5 * (z_component + rate_component)
        df = df.drop(columns=["signal_reasons", "signal_metrics"], errors="ignore")
        all_pairs = request.args.get("all", "").lower() in {"1", "true", "yes"}
        if not all_pairs:
            limit = int(request.args.get("limit", "500"))
            df = df.head(max(limit, 0)) if limit else df
        return jsonify(_df_to_records(df))

    @server.route("/api/signals", methods=["GET"])
    def signals_api():
        df = load_signals(paths.data_dir)
        limit = int(request.args.get("limit", "500"))
        df = df.head(max(limit, 0)) if limit else df
        return jsonify(_df_to_records(df))

    @server.route("/api/signals/active", methods=["GET"])
    def signals_active_api():
        with session_factory() as session:
            latest = load_latest_signal_run(session)
            if not latest:
                return jsonify([])
            rows = load_active_signals(session, latest.run_id)
            executions = load_open_executions(session)
            latest_exec: dict[tuple[str, str], object] = {}
            for exec_row in sorted(executions, key=lambda item: item.timestamp):
                key = (exec_row.stock_secid, exec_row.future_secid)
                latest_exec[key] = exec_row
            open_pairs = {
                key
                for key, exec_row in latest_exec.items()
                if str(exec_row.action).lower() != "exit"
            }
            actionable: list[dict[str, object]] = []
            for row in rows:
                key = (row.stock_secid, row.future_secid)
                is_open = key in open_pairs
                if row.action == "enter" and not is_open:
                    action = "enter"
                elif row.action == "exit" and is_open:
                    action = "exit"
                else:
                    continue
                actionable.append(
                    {
                        "run_id": row.run_id,
                        "timestamp": row.timestamp.isoformat(),
                        "stock": row.stock_secid,
                        "future": row.future_secid,
                        "signal_action": action,
                        "signal_direction": row.direction,
                        "signal_score": row.score,
                        "signal_reasons": row.reasons,
                        "signal_metrics": row.metrics,
                    }
                )
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
            return jsonify(
                [
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
                    for row in rows
                ]
            )

    @server.route("/api/signals/execute", methods=["POST"])
    def signals_execute_api():
        payload = request.get_json(silent=True) or {}
        payload["timestamp"] = datetime.now(timezone.utc)
        with session_factory() as session:
            store_signal_execution(session, payload["timestamp"], payload)
        return jsonify({"status": "ok"})

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
                        "action": row.action,
                        "price": row.price,
                        "quantity": row.quantity,
                        "side": row.side,
                        "status": row.status,
                        "note": row.note,
                    }
                    for row in rows
                ]
            )

    @server.route("/api/backtests", methods=["GET"])
    def backtests_api():
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

        series_df = build_spread_series(
            settings, stock, future, window_days=window_days, full_life=full_life
        )
        if series_df.empty:
            return jsonify([])
        series_df = series_df.copy()
        series_df["date"] = pd.to_datetime(series_df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        records = _df_to_records(series_df)
        _write_cache(cache_path, records)
        return jsonify(records)

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
