from __future__ import annotations

import statistics
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
from moex_carry.signal_engine.setups.extended_families import (
    _infer_tick_size_from_last_price,
    _potential_return_pct,
    _safe_non_negative_float,
)


def _reject(generator: Any, *, setup_kind: str, rule: str, **details: Any) -> None:
    record = getattr(generator, "_record_rejection", None)
    if callable(record):
        record(setup_kind=setup_kind, rule=rule, details=details or None)
    return None


def generate_volatility_compression_breakout(
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
        return _reject(generator, setup_kind="VOLATILITY_COMPRESSION_BREAKOUT", rule="missing_m5")
    rows = sorted([row for row in m5 if row.ts <= as_of_ts], key=lambda row: row.ts)
    if len(rows) < 8:
        return _reject(
            generator,
            setup_kind="VOLATILITY_COMPRESSION_BREAKOUT",
            rule="insufficient_rows",
            row_count=int(len(rows)),
        )
    same_day_rows = [row for row in rows if row.ts.date() == as_of_ts.date()]
    source_rows = same_day_rows if len(same_day_rows) >= 8 else rows
    lookback = max(int(generator.cfg.get("vol_comp_lookback_bars", 18)), 6)
    recent_bars = max(int(generator.cfg.get("vol_comp_recent_bars", 4)), 2)
    if recent_bars >= lookback:
        recent_bars = max(2, lookback // 3)
    if len(source_rows) < lookback:
        return _reject(
            generator,
            setup_kind="VOLATILITY_COMPRESSION_BREAKOUT",
            rule="insufficient_lookback_rows",
            row_count=int(len(source_rows)),
            lookback=int(lookback),
        )
    window = source_rows[-lookback:]
    bar_ranges = [max(float(row.high) - float(row.low), 0.0) for row in window]
    prior_ranges = bar_ranges[:-recent_bars]
    recent_ranges = bar_ranges[-recent_bars:]
    prior_median = float(statistics.median(prior_ranges)) if prior_ranges else 0.0
    recent_median = float(statistics.median(recent_ranges)) if recent_ranges else 0.0
    if prior_median <= 0.0:
        return _reject(
            generator,
            setup_kind="VOLATILITY_COMPRESSION_BREAKOUT",
            rule="prior_range_median_non_positive",
            prior_median=float(prior_median),
        )
    compression_ratio = float(recent_median / prior_median)
    max_ratio = _safe_non_negative_float(generator.cfg.get("vol_comp_max_recent_to_prev_ratio"), 0.65)
    if compression_ratio > max_ratio:
        return _reject(
            generator,
            setup_kind="VOLATILITY_COMPRESSION_BREAKOUT",
            rule="compression_ratio_too_high",
            compression_ratio=float(compression_ratio),
            max_ratio=float(max_ratio),
        )

    tick_size = _infer_tick_size_from_last_price(
        last_price_ticks=int(last_price_ticks),
        last_close=float(window[-1].close),
    )
    range_high_ticks = max(price_to_ticks(float(row.high), tick_size) for row in window)
    range_low_ticks = min(price_to_ticks(float(row.low), tick_size) for row in window)
    range_ticks = int(range_high_ticks) - int(range_low_ticks)
    if range_ticks <= 0:
        return _reject(
            generator,
            setup_kind="VOLATILITY_COMPRESSION_BREAKOUT",
            rule="range_non_positive",
            range_ticks=int(range_ticks),
        )
    atr_ref_ticks = max(int(regime.h1_atr_ticks), 1)
    min_range_mult = _safe_non_negative_float(generator.cfg.get("vol_comp_min_range_atr_mult"), 0.2)
    max_range_mult = max(
        _safe_non_negative_float(generator.cfg.get("vol_comp_max_range_atr_mult"), 1.8),
        float(min_range_mult),
    )
    min_range_ticks = max(round_half_away_from_zero(min_range_mult * float(atr_ref_ticks)), 1)
    max_range_ticks = max(round_half_away_from_zero(max_range_mult * float(atr_ref_ticks)), min_range_ticks)
    if int(range_ticks) < int(min_range_ticks):
        return _reject(
            generator,
            setup_kind="VOLATILITY_COMPRESSION_BREAKOUT",
            rule="range_below_min",
            range_ticks=int(range_ticks),
            min_range_ticks=int(min_range_ticks),
        )
    if int(range_ticks) > int(max_range_ticks):
        return _reject(
            generator,
            setup_kind="VOLATILITY_COMPRESSION_BREAKOUT",
            rule="range_above_max",
            range_ticks=int(range_ticks),
            max_range_ticks=int(max_range_ticks),
        )

    require_price_break = bool(generator.cfg.get("vol_comp_require_price_break", True))
    extra_buffer_ticks = max(int(generator.cfg.get("vol_comp_breakout_buffer_ticks", 0)), 0)
    if regime.daily_dir == Direction.UP:
        side = Side.BUY
        if require_price_break and int(last_price_ticks) < int(range_high_ticks):
            return _reject(
                generator,
                setup_kind="VOLATILITY_COMPRESSION_BREAKOUT",
                rule="price_not_breaking_up",
                last_price_ticks=int(last_price_ticks),
                range_high_ticks=int(range_high_ticks),
            )
        entry_stop_ticks = int(range_high_ticks) + int(exec_params.buffer_ticks) + int(extra_buffer_ticks)
        limit_ticks = int(entry_stop_ticks) + int(exec_params.limit_slip_ticks)
        level_kind = "VOL_COMP_H"
        level_price_ticks = int(range_high_ticks)
    elif regime.daily_dir == Direction.DOWN:
        side = Side.SELL
        if require_price_break and int(last_price_ticks) > int(range_low_ticks):
            return _reject(
                generator,
                setup_kind="VOLATILITY_COMPRESSION_BREAKOUT",
                rule="price_not_breaking_down",
                last_price_ticks=int(last_price_ticks),
                range_low_ticks=int(range_low_ticks),
            )
        entry_stop_ticks = int(range_low_ticks) - int(exec_params.buffer_ticks) - int(extra_buffer_ticks)
        limit_ticks = int(entry_stop_ticks) - int(exec_params.limit_slip_ticks)
        level_kind = "VOL_COMP_L"
        level_price_ticks = int(range_low_ticks)
    else:
        return _reject(generator, setup_kind="VOLATILITY_COMPRESSION_BREAKOUT", rule="daily_dir_neutral")

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
            setup_kind="VOLATILITY_COMPRESSION_BREAKOUT",
            rule="non_positive_risk_ticks",
            risk_ticks=int(risk_ticks),
        )
    max_risk_atr_mult = float(generator.cfg.get("max_risk_atr_mult", 1.2))
    if regime.h1_atr_ticks > 0:
        max_risk = max(round_half_away_from_zero(max_risk_atr_mult * float(regime.h1_atr_ticks)), 1)
        if risk_ticks > max_risk:
            return _reject(
                generator,
                setup_kind="VOLATILITY_COMPRESSION_BREAKOUT",
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
            setup_kind="VOLATILITY_COMPRESSION_BREAKOUT",
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
            setup_kind="VOLATILITY_COMPRESSION_BREAKOUT",
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
    setup_id = f"{instrument_id}:VOLATILITY_COMPRESSION_BREAKOUT:{side.value}:{entry_stop_ticks}"
    entry_level = Level(
        tf=TF.H1,
        kind=str(level_kind),
        price_ticks=int(level_price_ticks),
        score=0.79,
        meta={
            "compression_ratio": float(compression_ratio),
            "lookback_bars": int(lookback),
            "recent_bars": int(recent_bars),
            "range_ticks": int(range_ticks),
            "bar_ts": window[-1].ts.isoformat(),
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
                "setup_kind": "VOLATILITY_COMPRESSION_BREAKOUT",
                "cost_gate": cost_gate,
                "target_return_pct": float(target_return_pct),
                "stop_model": str(stop_model),
                "compression_ratio": float(compression_ratio),
                "range_ticks": int(range_ticks),
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
            meta={"setup_kind": "VOLATILITY_COMPRESSION_BREAKOUT", "stop_model": str(stop_model)},
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
            meta={"setup_kind": "VOLATILITY_COMPRESSION_BREAKOUT"},
        ),
        horizon=str(generator.cfg.get("horizon", "EOD")),
        rationale=[
            "trend_first",
            "volatility_compression_breakout",
            f"daily_dir_{regime.daily_dir.value.lower()}",
        ],
        risk_ticks=int(risk_ticks),
    )
