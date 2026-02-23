from __future__ import annotations

from datetime import datetime, timezone
import logging
import math
from typing import Callable

import pandas as pd
from flask import Flask, jsonify, request

from moex_carry.domain.pretrade_service import (
    PretradeRuntimeParams,
    enrich_pretrade_result,
    normalize_pretrade_direction,
)
from moex_carry.ui.data import load_top_pairs


def register_pretrade_routes(
    server: Flask,
    *,
    settings,
    paths,
    logger: logging.Logger,
    parse_float: Callable[[object, float], float],
    parse_int: Callable[[object, int], int],
    future_scale_from_raw: Callable[[object, str], float],
    bad_request: Callable[[str], object],
    sanitize_value: Callable[[object], object],
    build_pretrade_fail_open_result: Callable[..., dict[str, object]],
    is_iss_transport_error: Callable[[BaseException], bool],
    get_moex_client_cls: Callable[[], object],
    get_run_delay_gate: Callable[[], Callable[..., object]],
    observe_request: Callable[[str, datetime, object], object],
    mark_pretrade_events: Callable[[object], None],
) -> None:
    def _run_pretrade_check(payload: dict[str, object]):
        stock = str(payload.get("stock") or "").strip()
        future = str(payload.get("future") or "").strip()
        if not stock or not future:
            return jsonify({"error": "missing_params", "message": "stock and future are required"}), 400

        top_pairs = load_top_pairs(
            paths.data_dir,
            preferred_engine=("unified" if settings.ui.use_unified_signal_engine else None),
        )
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
            return bad_request("direction must be cash_and_carry or reverse")

        spot_default = None
        fut_default = None
        spread_default = None
        if row is not None:
            spot_default = row.get("spot")
            fut_default = row.get("future_price")
            spread_default = row.get("spread_mid")

        spot_target = parse_float(
            payload.get("spot_target"),
            float(spot_default) if pd.notna(spot_default) else float("nan"),
        )
        future_target = parse_float(
            payload.get("future_target"),
            float(fut_default) if pd.notna(fut_default) else float("nan"),
        )
        if math.isnan(spot_target) or math.isnan(future_target):
            return bad_request("spot_target and future_target are required if pair is absent in top_pairs")

        spread_fallback = spot_target - future_target
        spread_target = parse_float(
            payload.get("spread_target"),
            float(spread_default) if pd.notna(spread_default) else spread_fallback,
        )

        snapshots = max(parse_int(payload.get("snapshots"), 4), 1)
        snapshots = min(snapshots, 12)
        min_hits = max(parse_int(payload.get("min_hits"), 2), 1)
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
        eps = max(parse_float(payload.get("eps"), eps_default), 0.0001)
        eps = min(eps, 0.05)
        stock_eps = max(parse_float(payload.get("stock_eps"), stock_eps_default), 0.0001)
        stock_eps = min(stock_eps, 0.05)
        future_eps = max(parse_float(payload.get("future_eps"), future_eps_default), 0.0001)
        future_eps = min(future_eps, 0.05)
        spread_eps = max(parse_float(payload.get("spread_eps"), spread_eps_default), 0.0001)
        spread_eps = min(spread_eps, 0.05)
        sync_sec = max(parse_float(payload.get("sync_sec"), 120.0), 1.0)
        poll_sec = max(parse_float(payload.get("poll_sec"), 5.0), 0.0)
        poll_sec = min(poll_sec, 15.0)

        qty_fut_default = float(settings.spread_carry_alpha.max_contracts_per_pair or 1)
        qty_fut = max(parse_float(payload.get("qty_fut"), qty_fut_default), 0.0)
        participation_default = float(settings.spread_carry_alpha.participation_rate or 0.1)
        participation_rate = max(
            parse_float(payload.get("participation_rate"), participation_default),
            0.000001,
        )
        participation_rate = min(participation_rate, 1.0)

        future_scale = future_scale_from_raw(paths.data_dir / "raw" / "futures.csv", future)
        moex_client_cls = get_moex_client_cls()
        client = moex_client_cls(
            settings.moex.base_url,
            settings.moex.request_timeout_sec,
            max_retries=settings.moex.request_max_retries,
            retry_backoff_sec=settings.moex.request_retry_backoff_sec,
            retry_max_backoff_sec=settings.moex.request_retry_max_backoff_sec,
            fallback_ips=settings.moex.fallback_ips,
            force_fallback=settings.moex.force_fallback,
        )

        try:
            run_delay_gate_fn = get_run_delay_gate()
            result = run_delay_gate_fn(
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
            if settings.ui.pretrade_fail_open_on_transport_error and is_iss_transport_error(exc):
                logger.warning(
                    "Pretrade delay gate transport failure; returning fail-open response",
                    exc_info=True,
                )
                result = build_pretrade_fail_open_result(
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
        return jsonify(sanitize_value(enriched))

    @server.route("/api/pretrade/check", methods=["GET"])
    def pretrade_check_api():
        return _run_pretrade_check(dict(request.args.to_dict(flat=True)))

    @server.route("/api/v2/pretrade/check", methods=["POST"])
    def pretrade_check_v2_api():
        started_at = datetime.now(timezone.utc)
        payload = request.get_json(silent=True)
        if payload is None:
            return observe_request("v2_pretrade_check", started_at, bad_request("invalid_json"))
        if not isinstance(payload, dict):
            return observe_request(
                "v2_pretrade_check", started_at, bad_request("payload must be object")
            )
        result = _run_pretrade_check(dict(payload))
        mark_pretrade_events(result)
        return observe_request("v2_pretrade_check", started_at, result)
