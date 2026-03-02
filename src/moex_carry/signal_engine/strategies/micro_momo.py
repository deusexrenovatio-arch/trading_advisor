from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from moex_carry.signal_engine.core.types import AlphaProposal, Candle
from moex_carry.signal_engine.core.math_utils import round_half_away_from_zero
from moex_carry.signal_engine.features.ohlcv import atr_ticks, ema, relative_volume


@dataclass(frozen=True)
class MicroMomentumConfig:
    ema_fast: int = 9
    ema_slow: int = 21
    rel_volume_min: float = 1.2
    tp_atr_mult: float = 0.8
    sl_atr_mult: float = 0.6
    horizon_min: int = 60
    atr_period: int = 14
    rel_volume_window: int = 60


def generate_micro_momentum_proposal(
    *,
    instrument_id: str,
    candles: list[Candle],
    tick_size: float,
    config: MicroMomentumConfig = MicroMomentumConfig(),
    context: dict[str, Any] | None = None,
) -> AlphaProposal | None:
    context_data = context or {}
    closes = [float(candle.close) for candle in candles]
    volumes = [float(candle.volume) for candle in candles]
    if len(closes) < max(int(config.ema_slow), int(config.atr_period) + 2):
        return None

    ema_fast_value = ema(closes, int(config.ema_fast))
    ema_slow_value = ema(closes, int(config.ema_slow))
    if ema_fast_value is None or ema_slow_value is None:
        return None

    rel_volume_value = context_data.get("rel_volume")
    if rel_volume_value is None:
        rel_volume_value = relative_volume(volumes, window=int(config.rel_volume_window))
    if rel_volume_value is None or float(rel_volume_value) < float(config.rel_volume_min):
        return None

    if float(ema_fast_value) > float(ema_slow_value):
        side = "BUY"
    elif float(ema_fast_value) < float(ema_slow_value):
        side = "SELL"
    else:
        return None

    atr_ticks_value = context_data.get("atr_ticks")
    if atr_ticks_value is None:
        atr_ticks_value = atr_ticks(candles, tick_size=tick_size, period=int(config.atr_period))
    if atr_ticks_value is None:
        return None

    tp_ticks_value = max(
        round_half_away_from_zero(float(config.tp_atr_mult) * float(atr_ticks_value)),
        1,
    )
    sl_ticks_value = max(
        round_half_away_from_zero(float(config.sl_atr_mult) * float(atr_ticks_value)),
        1,
    )

    return AlphaProposal(
        strategy_id="micro_momo_v1",
        instrument_id=instrument_id,
        side=side,
        entry_ts=candles[-1].ts,
        horizon_sec=max(int(config.horizon_min), 1) * 60,
        tp_ticks=int(tp_ticks_value),
        sl_ticks=int(sl_ticks_value),
        exit_rule={"type": "ema_cross_or_time_exit"},
        features_snapshot={
            "ema_fast": float(ema_fast_value),
            "ema_slow": float(ema_slow_value),
            "rel_volume": float(rel_volume_value),
            "atr_ticks": float(atr_ticks_value),
        },
        market_regime_snapshot={},
    )
