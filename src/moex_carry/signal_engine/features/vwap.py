from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import mean

from moex_carry.signal_engine.core.types import Candle


def _typical_price(candle: Candle) -> float:
    return (float(candle.high) + float(candle.low) + float(candle.close)) / 3.0


def session_vwap(
    candles: Sequence[Candle],
    *,
    use_typical_price: bool = True,
) -> list[float]:
    if not candles:
        return []
    result: list[float] = []
    cum_pv = 0.0
    cum_v = 0.0
    active_day = candles[0].ts.date()
    for candle in candles:
        day = candle.ts.date()
        if day != active_day:
            active_day = day
            cum_pv = 0.0
            cum_v = 0.0
        price = _typical_price(candle) if use_typical_price else float(candle.close)
        volume = max(float(candle.volume), 0.0)
        cum_pv += price * volume
        cum_v += volume
        if cum_v <= 0:
            result.append(float(price))
            continue
        result.append(float(cum_pv / cum_v))
    return result


def vwap_deviation(prices: Sequence[float], vwaps: Sequence[float]) -> list[float]:
    size = min(len(prices), len(vwaps))
    return [float(prices[idx]) - float(vwaps[idx]) for idx in range(size)]


def vwap_zscore(prices: Sequence[float], vwaps: Sequence[float], window: int = 60) -> float | None:
    deviations = vwap_deviation(prices, vwaps)
    window_value = max(int(window), 1)
    if len(deviations) < window_value:
        return None
    work = deviations[-window_value:]
    mu = float(mean(work))
    variance = sum((value - mu) ** 2 for value in work) / float(window_value)
    sigma = math.sqrt(max(variance, 0.0))
    if sigma <= 0.0:
        return 0.0
    return float((work[-1] - mu) / sigma)
