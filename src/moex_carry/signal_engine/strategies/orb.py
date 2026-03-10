from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from moex_carry.signal_engine.core.math_utils import price_to_ticks, round_half_away_from_zero
from moex_carry.signal_engine.core.types import AlphaProposal, Candle
from moex_carry.signal_engine.features.ohlcv import atr_ticks


@dataclass(frozen=True)
class OrbConfig:
    opening_range_min: int = 15
    buffer_atr_mult: float = 0.10
    buffer_ticks_min: int = 1
    tp_atr_mult: float = 1.0
    sl_atr_mult: float = 0.7
    horizon_min: int = 90
    require_high_vol: bool = True
    atr_period: int = 14


def _latest_session_candles(candles: list[Candle]) -> list[Candle]:
    if not candles:
        return []
    active_day = candles[-1].ts.date()
    return [candle for candle in candles if candle.ts.date() == active_day]


def generate_orb_proposal(
    *,
    instrument_id: str,
    candles: list[Candle],
    tick_size: float,
    config: OrbConfig = OrbConfig(),
    context: dict[str, Any] | None = None,
) -> AlphaProposal | None:
    if len(candles) < max(config.opening_range_min + 1, 2):
        return None
    context_data = context or {}
    if config.require_high_vol and str(context_data.get("vol_regime", "")).upper() != "HIGH":
        return None

    session_candles = _latest_session_candles(candles)
    if len(session_candles) < max(config.opening_range_min + 1, 2):
        return None

    opening = session_candles[: config.opening_range_min]
    current = session_candles[-1]
    orb_high = max(float(candle.high) for candle in opening)
    orb_low = min(float(candle.low) for candle in opening)
    orb_high_ticks = price_to_ticks(orb_high, tick_size)
    orb_low_ticks = price_to_ticks(orb_low, tick_size)
    close_ticks = price_to_ticks(float(current.close), tick_size)

    atr_ticks_value = context_data.get("atr_ticks")
    if atr_ticks_value is None:
        atr_ticks_value = atr_ticks(session_candles, tick_size=tick_size, period=config.atr_period)
    if atr_ticks_value is None:
        return None
    atr_ticks_value = max(int(atr_ticks_value), 1)

    buffer_ticks = max(
        int(config.buffer_ticks_min),
        round_half_away_from_zero(float(config.buffer_atr_mult) * float(atr_ticks_value)),
    )
    tp_ticks_value = max(round_half_away_from_zero(float(config.tp_atr_mult) * float(atr_ticks_value)), 1)
    sl_ticks_value = max(round_half_away_from_zero(float(config.sl_atr_mult) * float(atr_ticks_value)), 1)

    if close_ticks >= orb_high_ticks + buffer_ticks:
        side = "BUY"
    elif close_ticks <= orb_low_ticks - buffer_ticks:
        side = "SELL"
    else:
        return None

    return AlphaProposal(
        strategy_id="orb_v1",
        instrument_id=instrument_id,
        side=side,
        entry_ts=current.ts,
        horizon_sec=max(int(config.horizon_min), 1) * 60,
        tp_ticks=tp_ticks_value,
        sl_ticks=sl_ticks_value,
        exit_rule={"type": "time_exit"},
        features_snapshot={
            "atr_ticks": float(atr_ticks_value),
            "orb_high_ticks": orb_high_ticks,
            "orb_low_ticks": orb_low_ticks,
            "buffer_ticks": buffer_ticks,
        },
        market_regime_snapshot={"vol_regime": context_data.get("vol_regime")},
    )
