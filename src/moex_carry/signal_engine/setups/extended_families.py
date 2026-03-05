from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from moex_carry.signal_engine.core.calendar import MarketCalendar
from moex_carry.signal_engine.core.math_utils import price_to_ticks, round_half_away_from_zero
from moex_carry.signal_engine.core.types import (
    Candle,
    Direction,
    ExecutionParams,
    Level,
    OrderIntent,
    OrderType,
    RegimeState,
    Setup,
    Side,
    TF,
)


def _reject(generator: Any, *, setup_kind: str, rule: str, **details: Any) -> None:
    record = getattr(generator, "_record_rejection", None)
    if callable(record):
        record(setup_kind=setup_kind, rule=rule, details=details or None)
    return None


def generate_orb_breakout(
    generator: Any,
    *,
    as_of_ts: datetime,
    instrument_id: str,
    last_price_ticks: int,
    regime: RegimeState,
    levels_d1: list[Level],
    exec_params: ExecutionParams,
    calendar: MarketCalendar,
    m5: list[Candle],
) -> Setup | None:
    if not m5:
        return _reject(generator, setup_kind="ORB_BREAKOUT", rule="missing_m5")
    same_day_rows = sorted(
        [row for row in m5 if row.ts <= as_of_ts and row.ts.date() == as_of_ts.date()],
        key=lambda row: row.ts,
    )
    if len(same_day_rows) < 2:
        return _reject(
            generator,
            setup_kind="ORB_BREAKOUT",
            rule="insufficient_same_day_rows",
            row_count=int(len(same_day_rows)),
        )
    opening_minutes = max(int(generator.cfg.get("orb_opening_range_minutes", 30)), 5)
    session_start = same_day_rows[0].ts
    opening_end = session_start + timedelta(minutes=opening_minutes)
    opening_rows = [row for row in same_day_rows if row.ts <= opening_end]
    if len(opening_rows) < 2:
        return _reject(
            generator,
            setup_kind="ORB_BREAKOUT",
            rule="insufficient_opening_rows",
            opening_row_count=int(len(opening_rows)),
        )
    inferred_tick_size = _infer_tick_size_from_last_price(
        last_price_ticks=int(last_price_ticks),
        last_close=float(same_day_rows[-1].close),
    )
    orb_high_ticks = max(price_to_ticks(float(row.high), inferred_tick_size) for row in opening_rows)
    orb_low_ticks = min(price_to_ticks(float(row.low), inferred_tick_size) for row in opening_rows)
    orb_range_ticks = max(int(orb_high_ticks) - int(orb_low_ticks), 1)
    atr_ref_ticks = max(int(regime.h1_atr_ticks), 1)
    min_range_mult = _safe_non_negative_float(generator.cfg.get("orb_min_range_atr_mult"), 0.1)
    max_range_mult = max(
        _safe_non_negative_float(generator.cfg.get("orb_max_range_atr_mult"), 1.8),
        float(min_range_mult),
    )
    min_range_ticks = max(round_half_away_from_zero(min_range_mult * float(atr_ref_ticks)), 1)
    max_range_ticks = max(round_half_away_from_zero(max_range_mult * float(atr_ref_ticks)), min_range_ticks)
    if int(orb_range_ticks) < int(min_range_ticks):
        return _reject(
            generator,
            setup_kind="ORB_BREAKOUT",
            rule="orb_range_below_min",
            orb_range_ticks=int(orb_range_ticks),
            min_range_ticks=int(min_range_ticks),
        )
    if int(orb_range_ticks) > int(max_range_ticks):
        return _reject(
            generator,
            setup_kind="ORB_BREAKOUT",
            rule="orb_range_above_max",
            orb_range_ticks=int(orb_range_ticks),
            max_range_ticks=int(max_range_ticks),
        )

    require_price_break = bool(generator.cfg.get("orb_require_price_break", True))
    if regime.daily_dir == Direction.UP:
        side = Side.BUY
        if require_price_break and int(last_price_ticks) < int(orb_high_ticks):
            return _reject(
                generator,
                setup_kind="ORB_BREAKOUT",
                rule="price_not_breaking_up",
                last_price_ticks=int(last_price_ticks),
                orb_high_ticks=int(orb_high_ticks),
            )
        entry_stop_ticks = int(orb_high_ticks) + int(exec_params.buffer_ticks)
        limit_ticks = int(entry_stop_ticks) + int(exec_params.limit_slip_ticks)
        level_kind = "ORB_H"
        level_price_ticks = int(orb_high_ticks)
    elif regime.daily_dir == Direction.DOWN:
        side = Side.SELL
        if require_price_break and int(last_price_ticks) > int(orb_low_ticks):
            return _reject(
                generator,
                setup_kind="ORB_BREAKOUT",
                rule="price_not_breaking_down",
                last_price_ticks=int(last_price_ticks),
                orb_low_ticks=int(orb_low_ticks),
            )
        entry_stop_ticks = int(orb_low_ticks) - int(exec_params.buffer_ticks)
        limit_ticks = int(entry_stop_ticks) - int(exec_params.limit_slip_ticks)
        level_kind = "ORB_L"
        level_price_ticks = int(orb_low_ticks)
    else:
        return _reject(generator, setup_kind="ORB_BREAKOUT", rule="daily_dir_neutral")

    sl_ticks, stop_model = generator._choose_stop_ticks(
        side=side,
        entry_ticks=entry_stop_ticks,
        regime=regime,
        exec_params=exec_params,
        m5=m5,
    )
    if side == Side.BUY and int(sl_ticks) >= int(entry_stop_ticks):
        sl_ticks = generator._volatility_stop_ticks(
            side=side,
            entry_ticks=entry_stop_ticks,
            regime=regime,
            exec_params=exec_params,
        )
        stop_model = "volatility_fallback"
    if side == Side.SELL and int(sl_ticks) <= int(entry_stop_ticks):
        sl_ticks = generator._volatility_stop_ticks(
            side=side,
            entry_ticks=entry_stop_ticks,
            regime=regime,
            exec_params=exec_params,
        )
        stop_model = "volatility_fallback"
    risk_ticks = abs(int(entry_stop_ticks) - int(sl_ticks))
    if risk_ticks <= 0:
        return _reject(
            generator,
            setup_kind="ORB_BREAKOUT",
            rule="non_positive_risk_ticks",
            risk_ticks=int(risk_ticks),
        )
    max_risk_atr_mult = float(generator.cfg.get("max_risk_atr_mult", 1.2))
    if regime.h1_atr_ticks > 0:
        max_risk = max(round_half_away_from_zero(max_risk_atr_mult * float(regime.h1_atr_ticks)), 1)
        if risk_ticks > max_risk:
            return _reject(
                generator,
                setup_kind="ORB_BREAKOUT",
                rule="risk_above_max_atr_mult",
                risk_ticks=int(risk_ticks),
                max_risk_ticks=int(max_risk),
            )

    min_target_ticks = int(generator.cfg.get("min_target_ticks", 3))
    tp_ticks = generator.execution_engine.choose_tp_from_levels(
        side=side,
        entry_ticks=entry_stop_ticks,
        candidate_levels=levels_d1,
        min_target_ticks=min_target_ticks,
    )
    if tp_ticks is None:
        rr_default = float(generator.cfg.get("rr_default", 1.6))
        delta = max(round_half_away_from_zero(rr_default * float(risk_ticks)), min_target_ticks)
        tp_ticks = entry_stop_ticks + delta if side == Side.BUY else entry_stop_ticks - delta
    target_return_pct = _potential_return_pct(entry_stop_ticks, tp_ticks)
    if float(target_return_pct) < float(generator._min_target_return_pct()):
        return _reject(
            generator,
            setup_kind="ORB_BREAKOUT",
            rule="target_return_pct_below_min",
            target_return_pct=float(target_return_pct),
            min_target_return_pct=float(generator._min_target_return_pct()),
        )

    cost_gate = generator._cost_gate_metrics(
        reward_gross_ticks=abs(int(tp_ticks) - int(entry_stop_ticks)),
        risk_gross_ticks=int(risk_ticks),
    )
    if generator._cost_gate_enabled() and not bool(cost_gate.get("pass")):
        return _reject(
            generator,
            setup_kind="ORB_BREAKOUT",
            rule="cost_gate_blocked",
            reward_net_ticks=float(cost_gate.get("reward_net_ticks", 0.0)),
            min_reward_net_ticks=float(cost_gate.get("min_reward_net_ticks", 0.0)),
            rr_net=float(cost_gate.get("rr_net", 0.0)),
            min_rr_net=float(cost_gate.get("min_rr_net", 0.0)),
        )

    expiry_policy = str(generator.cfg.get("entry_expiry_policy", "EOD_BEFORE_EVENING_CLEARING"))
    expiry_ts = calendar.recommended_entry_expiry(as_of_ts, expiry_policy)
    ttl_minutes = generator._entry_ttl_minutes()
    if ttl_minutes > 0:
        expiry_ts = min(expiry_ts, as_of_ts + timedelta(minutes=ttl_minutes))
    entry_range_low, entry_range_high = generator._entry_range_ticks(
        entry_ticks=entry_stop_ticks,
        order_type=OrderType.STOP_LIMIT,
        side=side,
        limit_ticks=limit_ticks,
    )
    setup_id = f"{instrument_id}:ORB_BREAKOUT:{side.value}:{entry_stop_ticks}"
    entry_level = Level(
        tf=TF.H1,
        kind=str(level_kind),
        price_ticks=int(level_price_ticks),
        score=0.86,
        meta={
            "orb_opening_range_minutes": int(opening_minutes),
            "orb_range_ticks": int(orb_range_ticks),
            "bar_ts": opening_rows[-1].ts.isoformat(),
        },
    )
    return Setup(
        setup_id=setup_id,
        side=side,
        entry_level=entry_level,
        entry_order=OrderIntent(
            order_type=OrderType.STOP_LIMIT,
            side=side,
            price_ticks=entry_stop_ticks,
            qty_lots=max(int(generator.cfg.get("qty_lots", 1)), 1),
            tif=str(generator.cfg.get("entry_tif", "GTT")),
            price_range_low_ticks=int(entry_range_low),
            price_range_high_ticks=int(entry_range_high),
            activate_from_ts=None,
            expire_ts=expiry_ts,
            link_group=setup_id,
            meta={
                "limit_price_ticks": int(limit_ticks),
                "setup_kind": "ORB_BREAKOUT",
                "cost_gate": cost_gate,
                "target_return_pct": float(target_return_pct),
                "stop_model": str(stop_model),
                "orb_opening_range_minutes": int(opening_minutes),
                "orb_range_ticks": int(orb_range_ticks),
                "entry_range_low_ticks": int(entry_range_low),
                "entry_range_high_ticks": int(entry_range_high),
                "stop_limit_fallback_to_market_min": int(generator._stop_limit_fallback_to_market_min()),
                "stop_limit_fallback_slip_ticks": int(generator._stop_limit_fallback_slip_ticks()),
                "time_stop_minutes": int(generator._time_stop_minutes()),
            },
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL if side == Side.BUY else Side.BUY,
            price_ticks=int(sl_ticks),
            qty_lots=max(int(generator.cfg.get("qty_lots", 1)), 1),
            tif="GTC",
            activate_from_ts=None,
            expire_ts=None,
            link_group=setup_id,
            meta={"setup_kind": "ORB_BREAKOUT", "stop_model": str(stop_model)},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL if side == Side.BUY else Side.BUY,
            price_ticks=int(tp_ticks),
            qty_lots=max(int(generator.cfg.get("qty_lots", 1)), 1),
            tif="GTC",
            activate_from_ts=None,
            expire_ts=None,
            link_group=setup_id,
            meta={"setup_kind": "ORB_BREAKOUT"},
        ),
        horizon=str(generator.cfg.get("horizon", "EOD")),
        rationale=[
            "trend_first",
            "orb_breakout",
            f"daily_dir_{regime.daily_dir.value.lower()}",
        ],
        risk_ticks=int(risk_ticks),
    )


def generate_ema_pullback_limit(
    generator: Any,
    *,
    as_of_ts: datetime,
    instrument_id: str,
    last_price_ticks: int,
    regime: RegimeState,
    levels_d1: list[Level],
    levels_h1: list[Level],
    exec_params: ExecutionParams,
    calendar: MarketCalendar,
    m5: list[Candle],
) -> Setup | None:
    ema_level = next((item for item in levels_h1 if str(item.kind) == "EMA20_H1"), None)
    if ema_level is None:
        return _reject(generator, setup_kind="EMA_PULLBACK_LIMIT", rule="missing_ema20_level")
    side = Side.BUY if regime.daily_dir == Direction.UP else Side.SELL
    if side == Side.BUY and int(ema_level.price_ticks) > int(last_price_ticks):
        return _reject(
            generator,
            setup_kind="EMA_PULLBACK_LIMIT",
            rule="ema_above_last_price_for_buy",
            ema_ticks=int(ema_level.price_ticks),
            last_price_ticks=int(last_price_ticks),
        )
    if side == Side.SELL and int(ema_level.price_ticks) < int(last_price_ticks):
        return _reject(
            generator,
            setup_kind="EMA_PULLBACK_LIMIT",
            rule="ema_below_last_price_for_sell",
            ema_ticks=int(ema_level.price_ticks),
            last_price_ticks=int(last_price_ticks),
        )
    max_dist_mult = float(generator.cfg.get("ema_pullback_max_dist_atr_mult", 1.0))
    max_dist_ticks = max(round_half_away_from_zero(max_dist_mult * float(max(regime.h1_atr_ticks, 1))), 1)
    if abs(int(last_price_ticks) - int(ema_level.price_ticks)) > int(max_dist_ticks):
        return _reject(
            generator,
            setup_kind="EMA_PULLBACK_LIMIT",
            rule="entry_level_too_far_from_last_price",
            distance_ticks=int(abs(int(last_price_ticks) - int(ema_level.price_ticks))),
            max_dist_ticks=int(max_dist_ticks),
        )
    entry_offset_ticks = int(generator.cfg.get("ema_pullback_offset_ticks", 0))
    entry_ticks = (
        int(ema_level.price_ticks) + int(entry_offset_ticks)
        if side == Side.BUY
        else int(ema_level.price_ticks) - int(entry_offset_ticks)
    )
    sl_ticks, stop_model = generator._choose_stop_ticks(
        side=side,
        entry_ticks=entry_ticks,
        regime=regime,
        exec_params=exec_params,
        m5=m5,
    )
    if side == Side.BUY and int(sl_ticks) >= int(entry_ticks):
        sl_ticks = generator._volatility_stop_ticks(
            side=side,
            entry_ticks=entry_ticks,
            regime=regime,
            exec_params=exec_params,
        )
        stop_model = "volatility_fallback"
    if side == Side.SELL and int(sl_ticks) <= int(entry_ticks):
        sl_ticks = generator._volatility_stop_ticks(
            side=side,
            entry_ticks=entry_ticks,
            regime=regime,
            exec_params=exec_params,
        )
        stop_model = "volatility_fallback"
    risk_ticks = abs(int(entry_ticks) - int(sl_ticks))
    if risk_ticks <= 0:
        return _reject(
            generator,
            setup_kind="EMA_PULLBACK_LIMIT",
            rule="non_positive_risk_ticks",
            risk_ticks=int(risk_ticks),
        )
    max_risk_atr_mult = float(generator.cfg.get("max_risk_atr_mult", 1.2))
    if regime.h1_atr_ticks > 0:
        max_risk = max(round_half_away_from_zero(max_risk_atr_mult * float(regime.h1_atr_ticks)), 1)
        if risk_ticks > max_risk:
            return _reject(
                generator,
                setup_kind="EMA_PULLBACK_LIMIT",
                rule="risk_above_max_atr_mult",
                risk_ticks=int(risk_ticks),
                max_risk_ticks=int(max_risk),
            )

    min_target_ticks = int(generator.cfg.get("min_target_ticks", 3))
    tp_ticks = generator.execution_engine.choose_tp_from_levels(
        side=side,
        entry_ticks=entry_ticks,
        candidate_levels=levels_d1,
        min_target_ticks=min_target_ticks,
    )
    if tp_ticks is None:
        rr_default = float(generator.cfg.get("rr_default", 1.6))
        delta = max(round_half_away_from_zero(rr_default * float(risk_ticks)), min_target_ticks)
        tp_ticks = entry_ticks + delta if side == Side.BUY else entry_ticks - delta
    target_return_pct = _potential_return_pct(entry_ticks, tp_ticks)
    if float(target_return_pct) < float(generator._min_target_return_pct()):
        return _reject(
            generator,
            setup_kind="EMA_PULLBACK_LIMIT",
            rule="target_return_pct_below_min",
            target_return_pct=float(target_return_pct),
            min_target_return_pct=float(generator._min_target_return_pct()),
        )

    cost_gate = generator._cost_gate_metrics(
        reward_gross_ticks=abs(int(tp_ticks) - int(entry_ticks)),
        risk_gross_ticks=int(risk_ticks),
    )
    if generator._cost_gate_enabled() and not bool(cost_gate.get("pass")):
        return _reject(
            generator,
            setup_kind="EMA_PULLBACK_LIMIT",
            rule="cost_gate_blocked",
            reward_net_ticks=float(cost_gate.get("reward_net_ticks", 0.0)),
            min_reward_net_ticks=float(cost_gate.get("min_reward_net_ticks", 0.0)),
            rr_net=float(cost_gate.get("rr_net", 0.0)),
            min_rr_net=float(cost_gate.get("min_rr_net", 0.0)),
        )

    expiry_policy = str(generator.cfg.get("entry_expiry_policy", "EOD_BEFORE_EVENING_CLEARING"))
    expiry_ts = calendar.recommended_entry_expiry(as_of_ts, expiry_policy)
    ttl_minutes = generator._entry_ttl_minutes()
    if ttl_minutes > 0:
        expiry_ts = min(expiry_ts, as_of_ts + timedelta(minutes=ttl_minutes))
    entry_range_low, entry_range_high = generator._entry_range_ticks(
        entry_ticks=entry_ticks,
        order_type=OrderType.LIMIT,
        side=side,
    )
    setup_id = f"{instrument_id}:EMA_PULLBACK_LIMIT:{side.value}:{entry_ticks}"
    return Setup(
        setup_id=setup_id,
        side=side,
        entry_level=ema_level,
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=side,
            price_ticks=int(entry_ticks),
            qty_lots=max(int(generator.cfg.get("qty_lots", 1)), 1),
            tif=str(generator.cfg.get("entry_tif", "GTT")),
            price_range_low_ticks=int(entry_range_low),
            price_range_high_ticks=int(entry_range_high),
            activate_from_ts=None,
            expire_ts=expiry_ts,
            link_group=setup_id,
            meta={
                "setup_kind": "EMA_PULLBACK_LIMIT",
                "cost_gate": cost_gate,
                "target_return_pct": float(target_return_pct),
                "stop_model": str(stop_model),
                "entry_range_low_ticks": int(entry_range_low),
                "entry_range_high_ticks": int(entry_range_high),
                "time_stop_minutes": int(generator._time_stop_minutes()),
            },
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL if side == Side.BUY else Side.BUY,
            price_ticks=int(sl_ticks),
            qty_lots=max(int(generator.cfg.get("qty_lots", 1)), 1),
            tif="GTC",
            activate_from_ts=None,
            expire_ts=None,
            link_group=setup_id,
            meta={"setup_kind": "EMA_PULLBACK_LIMIT", "stop_model": str(stop_model)},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL if side == Side.BUY else Side.BUY,
            price_ticks=int(tp_ticks),
            qty_lots=max(int(generator.cfg.get("qty_lots", 1)), 1),
            tif="GTC",
            activate_from_ts=None,
            expire_ts=None,
            link_group=setup_id,
            meta={"setup_kind": "EMA_PULLBACK_LIMIT"},
        ),
        horizon=str(generator.cfg.get("horizon", "EOD")),
        rationale=[
            "trend_first",
            "ema20_pullback",
            f"daily_dir_{regime.daily_dir.value.lower()}",
        ],
        risk_ticks=int(risk_ticks),
    )


def generate_vwap_pullback_limit(
    generator: Any,
    *,
    as_of_ts: datetime,
    instrument_id: str,
    last_price_ticks: int,
    regime: RegimeState,
    levels_d1: list[Level],
    exec_params: ExecutionParams,
    calendar: MarketCalendar,
    m5: list[Candle],
) -> Setup | None:
    if not m5:
        return _reject(generator, setup_kind="VWAP_PULLBACK_LIMIT", rule="missing_m5")
    same_day_rows = sorted(
        [row for row in m5 if row.ts <= as_of_ts and row.ts.date() == as_of_ts.date()],
        key=lambda row: row.ts,
    )
    vwap_rows = list(same_day_rows)
    if len(vwap_rows) < 3:
        recent_rows = sorted([row for row in m5 if row.ts <= as_of_ts], key=lambda row: row.ts)
        vwap_rows = recent_rows[-24:]
    if len(vwap_rows) < 3:
        return _reject(
            generator,
            setup_kind="VWAP_PULLBACK_LIMIT",
            rule="insufficient_rows_for_vwap",
            row_count=int(len(vwap_rows)),
        )
    tick_size = _infer_tick_size_from_last_price(
        last_price_ticks=int(last_price_ticks),
        last_close=float(vwap_rows[-1].close),
    )
    vwap_price = _session_vwap_price(vwap_rows)
    if vwap_price <= 0.0:
        return _reject(generator, setup_kind="VWAP_PULLBACK_LIMIT", rule="non_positive_vwap_price")
    vwap_ticks = int(price_to_ticks(vwap_price, tick_size))
    side = Side.BUY if regime.daily_dir == Direction.UP else Side.SELL
    require_alignment = bool(generator.cfg.get("vwap_require_side_alignment", True))
    if require_alignment:
        if side == Side.BUY and int(last_price_ticks) < int(vwap_ticks):
            return _reject(
                generator,
                setup_kind="VWAP_PULLBACK_LIMIT",
                rule="vwap_side_alignment_failed_buy",
                last_price_ticks=int(last_price_ticks),
                vwap_ticks=int(vwap_ticks),
            )
        if side == Side.SELL and int(last_price_ticks) > int(vwap_ticks):
            return _reject(
                generator,
                setup_kind="VWAP_PULLBACK_LIMIT",
                rule="vwap_side_alignment_failed_sell",
                last_price_ticks=int(last_price_ticks),
                vwap_ticks=int(vwap_ticks),
            )
    max_dist_mult = float(generator.cfg.get("vwap_pullback_max_dist_atr_mult", 1.2))
    max_dist_ticks = max(round_half_away_from_zero(max_dist_mult * float(max(regime.h1_atr_ticks, 1))), 1)
    if abs(int(last_price_ticks) - int(vwap_ticks)) > int(max_dist_ticks):
        return _reject(
            generator,
            setup_kind="VWAP_PULLBACK_LIMIT",
            rule="entry_level_too_far_from_last_price",
            distance_ticks=int(abs(int(last_price_ticks) - int(vwap_ticks))),
            max_dist_ticks=int(max_dist_ticks),
        )
    entry_offset_ticks = int(generator.cfg.get("vwap_pullback_offset_ticks", 0))
    entry_ticks = int(vwap_ticks + entry_offset_ticks) if side == Side.BUY else int(vwap_ticks - entry_offset_ticks)
    sl_ticks, stop_model = generator._choose_stop_ticks(
        side=side,
        entry_ticks=entry_ticks,
        regime=regime,
        exec_params=exec_params,
        m5=m5,
    )
    if side == Side.BUY and int(sl_ticks) >= int(entry_ticks):
        sl_ticks = generator._volatility_stop_ticks(
            side=side,
            entry_ticks=entry_ticks,
            regime=regime,
            exec_params=exec_params,
        )
        stop_model = "volatility_fallback"
    if side == Side.SELL and int(sl_ticks) <= int(entry_ticks):
        sl_ticks = generator._volatility_stop_ticks(
            side=side,
            entry_ticks=entry_ticks,
            regime=regime,
            exec_params=exec_params,
        )
        stop_model = "volatility_fallback"
    risk_ticks = abs(int(entry_ticks) - int(sl_ticks))
    if risk_ticks <= 0:
        return _reject(
            generator,
            setup_kind="VWAP_PULLBACK_LIMIT",
            rule="non_positive_risk_ticks",
            risk_ticks=int(risk_ticks),
        )
    max_risk_atr_mult = float(generator.cfg.get("max_risk_atr_mult", 1.2))
    if regime.h1_atr_ticks > 0:
        max_risk = max(round_half_away_from_zero(max_risk_atr_mult * float(regime.h1_atr_ticks)), 1)
        if risk_ticks > max_risk:
            return _reject(
                generator,
                setup_kind="VWAP_PULLBACK_LIMIT",
                rule="risk_above_max_atr_mult",
                risk_ticks=int(risk_ticks),
                max_risk_ticks=int(max_risk),
            )

    min_target_ticks = int(generator.cfg.get("min_target_ticks", 3))
    tp_ticks = generator.execution_engine.choose_tp_from_levels(
        side=side,
        entry_ticks=entry_ticks,
        candidate_levels=levels_d1,
        min_target_ticks=min_target_ticks,
    )
    if tp_ticks is None:
        rr_default = float(generator.cfg.get("rr_default", 1.6))
        delta = max(round_half_away_from_zero(rr_default * float(risk_ticks)), min_target_ticks)
        tp_ticks = entry_ticks + delta if side == Side.BUY else entry_ticks - delta
    target_return_pct = _potential_return_pct(entry_ticks, tp_ticks)
    if float(target_return_pct) < float(generator._min_target_return_pct()):
        return _reject(
            generator,
            setup_kind="VWAP_PULLBACK_LIMIT",
            rule="target_return_pct_below_min",
            target_return_pct=float(target_return_pct),
            min_target_return_pct=float(generator._min_target_return_pct()),
        )

    cost_gate = generator._cost_gate_metrics(
        reward_gross_ticks=abs(int(tp_ticks) - int(entry_ticks)),
        risk_gross_ticks=int(risk_ticks),
    )
    if generator._cost_gate_enabled() and not bool(cost_gate.get("pass")):
        return _reject(
            generator,
            setup_kind="VWAP_PULLBACK_LIMIT",
            rule="cost_gate_blocked",
            reward_net_ticks=float(cost_gate.get("reward_net_ticks", 0.0)),
            min_reward_net_ticks=float(cost_gate.get("min_reward_net_ticks", 0.0)),
            rr_net=float(cost_gate.get("rr_net", 0.0)),
            min_rr_net=float(cost_gate.get("min_rr_net", 0.0)),
        )

    expiry_policy = str(generator.cfg.get("entry_expiry_policy", "EOD_BEFORE_EVENING_CLEARING"))
    expiry_ts = calendar.recommended_entry_expiry(as_of_ts, expiry_policy)
    ttl_minutes = generator._entry_ttl_minutes()
    if ttl_minutes > 0:
        expiry_ts = min(expiry_ts, as_of_ts + timedelta(minutes=ttl_minutes))
    entry_range_low, entry_range_high = generator._entry_range_ticks(
        entry_ticks=entry_ticks,
        order_type=OrderType.LIMIT,
        side=side,
    )
    setup_id = f"{instrument_id}:VWAP_PULLBACK_LIMIT:{side.value}:{entry_ticks}"
    entry_level = Level(
        tf=TF.H1,
        kind="VWAP_M5",
        price_ticks=int(vwap_ticks),
        score=0.72,
        meta={
            "vwap_price": float(vwap_price),
            "vwap_ticks": int(vwap_ticks),
            "bar_ts": vwap_rows[-1].ts.isoformat(),
        },
    )
    return Setup(
        setup_id=setup_id,
        side=side,
        entry_level=entry_level,
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=side,
            price_ticks=int(entry_ticks),
            qty_lots=max(int(generator.cfg.get("qty_lots", 1)), 1),
            tif=str(generator.cfg.get("entry_tif", "GTT")),
            price_range_low_ticks=int(entry_range_low),
            price_range_high_ticks=int(entry_range_high),
            activate_from_ts=None,
            expire_ts=expiry_ts,
            link_group=setup_id,
            meta={
                "setup_kind": "VWAP_PULLBACK_LIMIT",
                "cost_gate": cost_gate,
                "target_return_pct": float(target_return_pct),
                "stop_model": str(stop_model),
                "entry_range_low_ticks": int(entry_range_low),
                "entry_range_high_ticks": int(entry_range_high),
                "time_stop_minutes": int(generator._time_stop_minutes()),
            },
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL if side == Side.BUY else Side.BUY,
            price_ticks=int(sl_ticks),
            qty_lots=max(int(generator.cfg.get("qty_lots", 1)), 1),
            tif="GTC",
            activate_from_ts=None,
            expire_ts=None,
            link_group=setup_id,
            meta={"setup_kind": "VWAP_PULLBACK_LIMIT", "stop_model": str(stop_model)},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL if side == Side.BUY else Side.BUY,
            price_ticks=int(tp_ticks),
            qty_lots=max(int(generator.cfg.get("qty_lots", 1)), 1),
            tif="GTC",
            activate_from_ts=None,
            expire_ts=None,
            link_group=setup_id,
            meta={"setup_kind": "VWAP_PULLBACK_LIMIT"},
        ),
        horizon=str(generator.cfg.get("horizon", "EOD")),
        rationale=[
            "trend_first",
            "vwap_pullback",
            f"daily_dir_{regime.daily_dir.value.lower()}",
        ],
        risk_ticks=int(risk_ticks),
    )


def _safe_non_negative_float(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    if parsed < 0.0:
        return 0.0
    return float(parsed)


def _infer_tick_size_from_last_price(*, last_price_ticks: int, last_close: float) -> float:
    if int(last_price_ticks) == 0:
        return 1.0
    inferred = abs(float(last_close)) / float(abs(int(last_price_ticks)))
    if inferred <= 0.0:
        return 1.0
    return float(inferred)


def _potential_return_pct(entry_ticks: int, tp_ticks: int) -> float:
    base = max(abs(int(entry_ticks)), 1)
    distance = abs(int(tp_ticks) - int(entry_ticks))
    return float(100.0 * distance / base)


def _session_vwap_price(rows: list[Candle]) -> float:
    weighted_sum = 0.0
    volume_sum = 0.0
    for row in rows:
        vol = max(float(row.volume), 0.0)
        if vol <= 0.0:
            continue
        typical = (float(row.high) + float(row.low) + float(row.close)) / 3.0
        weighted_sum += typical * vol
        volume_sum += vol
    if volume_sum <= 0.0:
        return 0.0
    return float(weighted_sum / volume_sum)
