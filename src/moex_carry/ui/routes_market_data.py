from __future__ import annotations

import logging
from typing import Callable
import uuid

import pandas as pd
from flask import Flask, jsonify, request


def register_market_data_routes(
    server: Flask,
    *,
    settings,
    paths,
    logger: logging.Logger,
    session_factory,
    cache_version: str,
    parse_date_bound: Callable[[str, str], object],
    merge_signal_metrics: Callable[[dict[str, object]], dict[str, object]],
    bad_request: Callable[[str], object],
    extract_response_payload: Callable[[object], tuple[object, int]],
    record_signal_action: Callable[..., object],
    normalize_execution_action: Callable[[object], str],
    load_signal_history_fn: Callable[..., list[object]],
    load_signal_executions_fn: Callable[..., list[object]],
    load_backtest_summary_fn: Callable[[object], pd.DataFrame],
    load_latest_unified_output: Callable[..., tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]],
    resolved_unified_max_pairs: Callable[[int | None], int | None],
    df_to_records: Callable[[pd.DataFrame], list[dict[str, object]]],
    parse_int: Callable[[object, int], int],
    signals_active_api: Callable[[], object],
    derive_lifecycle_state: Callable[[dict[str, object]], str],
    build_pair_entity_ref: Callable[[object, object], dict[str, object]],
    build_signal_id_from_row: Callable[[dict[str, object]], str],
    iso_now: Callable[[], str],
    append_jsonl: Callable[[object, dict[str, object]], None],
    stringify_datetime_columns: Callable[[pd.DataFrame], pd.DataFrame],
    read_cache: Callable[[object, int], list[dict[str, object]] | None],
    write_cache: Callable[[object, list[dict[str, object]]], None],
    unified_ttl_sec: Callable[[], int],
    build_unified_spread_series_fn: Callable[..., pd.DataFrame],
    get_build_spread_series: Callable[[], Callable[..., pd.DataFrame]],
) -> None:
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
        from_ts = parse_date_bound(from_raw, "start") if from_raw else None
        to_ts = parse_date_bound(to_raw, "end") if to_raw else None
        if from_raw and from_ts is None:
            return jsonify({"error": "invalid_from"}), 400
        if to_raw and to_ts is None:
            return jsonify({"error": "invalid_to"}), 400
        with session_factory() as session:
            rows = load_signal_history_fn(
                session,
                from_ts=from_ts,
                to_ts=to_ts,
                limit=limit,
                stock=stock,
                future=future,
                action=action,
            )
            payload = [
                merge_signal_metrics(
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
            return bad_request("invalid_json")
        result = record_signal_action(
            signal_id=None,
            payload=dict(payload),
            source_default="v1_adapter",
            legacy_mode=True,
        )
        response_payload, status_code = extract_response_payload(result)
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
            rows = load_signal_executions_fn(session, stock=stock, future=future, limit=limit)
            return jsonify(
                [
                    {
                        "timestamp": row.timestamp.isoformat(),
                        "stock": row.stock_secid,
                        "future": row.future_secid,
                        "direction": row.direction,
                        "action": normalize_execution_action(row.action),
                        "price": row.price,
                        "quantity": row.quantity,
                        "side": row.side,
                        "order_id": row.order_id,
                        "idempotency_key": row.idempotency_key,
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
                _, _, backtests = load_latest_unified_output(
                    max_pairs=resolved_unified_max_pairs(limit),
                    fresh=fresh,
                )
                df = backtests.copy()
            except Exception:
                logger.exception("Unified backtests failed")
                if not settings.ui.unified_allow_legacy_fallback:
                    return jsonify({"error": "server_error", "message": "unified_backtests_failed"}), 500
        if df.empty and settings.ui.unified_allow_legacy_fallback:
            df = load_backtest_summary_fn(paths.data_dir)
        limit = int(request.args.get("limit", "500"))
        df = df.head(max(limit, 0)) if limit else df
        return jsonify(df_to_records(df))

    @server.route("/api/v2/portfolio/rebalance/preview", methods=["GET"])
    def rebalance_preview_v2_api():
        limit = max(parse_int(request.args.get("limit"), 12), 1)
        legacy = signals_active_api()
        rows, status_code = extract_response_payload(legacy)
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
        active_for_weight = [
            row for row in selected if str(row.get("signal_action")).lower() in {"enter", "hold_open"}
        ]
        equal_weight = 1.0 / len(active_for_weight) if active_for_weight else 0.0

        positions: list[dict[str, object]] = []
        for row in selected:
            signal_action = str(row.get("signal_action") or "").strip().lower()
            lifecycle_state = derive_lifecycle_state(row)
            target_weight = equal_weight if signal_action in {"enter", "hold_open"} else 0.0
            positions.append(
                {
                    "entity_ref": build_pair_entity_ref(row.get("stock"), row.get("future")),
                    "target_weight": target_weight,
                    "signal_id": build_signal_id_from_row(row),
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
                "generated_at": iso_now(),
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
            return bad_request("invalid_json")
        plan_id = str(payload.get("rebalance_plan_id") or "").strip()
        if not plan_id:
            return bad_request("rebalance_plan_id is required")
        positions = payload.get("positions")
        if not isinstance(positions, list):
            return bad_request("positions must be a list")
        max_positions = int(settings.risk_profile.max_positions or 0)
        active_positions = 0
        for position in positions:
            if not isinstance(position, dict):
                continue
            signal_action = str(position.get("signal_action") or "").strip().lower()
            if signal_action in {"enter", "hold_open"}:
                active_positions += 1
                continue
            try:
                target_weight = float(position.get("target_weight") or 0.0)
            except (TypeError, ValueError):
                target_weight = 0.0
            if target_weight > 0:
                active_positions += 1
        risk_check = {
            "check": "max_positions",
            "passed": active_positions <= max_positions if max_positions > 0 else True,
            "limit": max_positions if max_positions > 0 else None,
            "value": active_positions,
        }
        if risk_check["passed"] is False:
            return (
                jsonify(
                    {
                        "status": "blocked",
                        "error": "risk_gate_failed",
                        "message": "max_positions risk gate failed",
                        "rebalance_plan_id": plan_id,
                        "risk_checks": [risk_check],
                    }
                ),
                409,
            )
        actor_id = str(payload.get("actor_id") or "operator").strip() or "operator"
        commit_id = f"rebal-commit-{uuid.uuid4().hex[:12]}"
        entry = {
            "commit_id": commit_id,
            "rebalance_plan_id": plan_id,
            "actor_id": actor_id,
            "positions": positions,
            "committed_at": iso_now(),
            "note": payload.get("note"),
        }
        commits_path = paths.data_dir / "portfolio" / "rebalance_commits.jsonl"
        append_jsonl(commits_path, entry)
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
        cache_path = cache_dir / f"spread_{stock}_{future}_{cache_suffix}_{cache_version}.json"
        cached = read_cache(cache_path, ttl_minutes=60)
        if cached is not None:
            return jsonify(cached)

        series_df = pd.DataFrame()
        if settings.ui.use_unified_signal_engine:
            try:
                series_df = build_unified_spread_series_fn(
                    settings,
                    paths.data_dir,
                    stock=stock,
                    future=future,
                    window_days=window_days,
                    full_life=full_life,
                    ttl_sec=unified_ttl_sec(),
                )
            except Exception:
                logger.exception("Unified spread-series failed")
                if not settings.ui.unified_allow_legacy_fallback:
                    return jsonify({"error": "server_error", "message": "unified_spread_series_failed"}), 500
        if series_df.empty and settings.ui.unified_allow_legacy_fallback:
            build_spread_series_fn = get_build_spread_series()
            series_df = build_spread_series_fn(
                settings, stock, future, window_days=window_days, full_life=full_life
            )
        if series_df.empty:
            return jsonify([])
        series_df = stringify_datetime_columns(series_df)
        records = df_to_records(series_df)
        write_cache(cache_path, records)
        return jsonify(records)
