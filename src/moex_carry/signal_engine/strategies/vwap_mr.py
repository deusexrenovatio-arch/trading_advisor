from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from moex_carry.signal_engine.core.math_utils import price_to_ticks, round_half_away_from_zero
from moex_carry.signal_engine.core.types import AlphaProposal, Candle
from moex_carry.signal_engine.features.ohlcv import atr_ticks
from moex_carry.signal_engine.features.vwap import session_vwap, vwap_zscore


@dataclass(frozen=True)
class VwapMeanReversionConfig:
    z_enter: float = 2.0
    z_exit: float = 0.5
    sl_atr_mult: float = 0.8
    min_tp_ticks: int = 2
    horizon_min: int = 45
    z_window: int = 60
    atr_period: int = 14


def generate_vwap_mr_proposal(
    *,
    instrument_id: str,
    candles: list[Candle],
    tick_size: float,
    config: VwapMeanReversionConfig = VwapMeanReversionConfig(),
    context: dict[str, Any] | None = None,
) -> AlphaProposal | None:
    context_data = context or {}
    if context_data.get("vacuum") is True:
        return None
    if len(candles) < max(int(config.z_window), int(config.atr_period) + 2):
        return None

    closes = [float(candle.close) for candle in candles]
    vwaps = session_vwap(candles)
    z_value = context_data.get("z_vwap")
    if z_value is None:
        z_value = vwap_zscore(closes, vwaps, window=int(config.z_window))
    if z_value is None:
        return None

    if float(z_value) <= -float(config.z_enter):
        side = "BUY"
    elif float(z_value) >= float(config.z_enter):
        side = "SELL"
    else:
        return None

    current = candles[-1]
    entry_ticks = price_to_ticks(float(current.close), tick_size)
    vwap_ticks = price_to_ticks(float(vwaps[-1]), tick_size)
    tp_ticks_value = max(int(config.min_tp_ticks), abs(int(vwap_ticks) - int(entry_ticks)))

    atr_ticks_value = context_data.get("atr_ticks")
    if atr_ticks_value is None:
        atr_ticks_value = atr_ticks(candles, tick_size=tick_size, period=int(config.atr_period))
    if atr_ticks_value is None:
        return None
    sl_ticks_value = max(
        round_half_away_from_zero(float(config.sl_atr_mult) * float(atr_ticks_value)),
        1,
    )

    return AlphaProposal(
        strategy_id="vwap_mr_v1",
        instrument_id=instrument_id,
        side=side,
        entry_ts=current.ts,
        horizon_sec=max(int(config.horizon_min), 1) * 60,
        tp_ticks=int(tp_ticks_value),
        sl_ticks=int(sl_ticks_value),
        exit_rule={"type": "z_or_time_exit", "z_exit": float(config.z_exit)},
        features_snapshot={
            "z_vwap": float(z_value),
            "entry_ticks": int(entry_ticks),
            "vwap_ticks": int(vwap_ticks),
            "atr_ticks": float(atr_ticks_value),
        },
        market_regime_snapshot={},
    )
