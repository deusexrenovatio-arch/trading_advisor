from __future__ import annotations

import math
from collections.abc import Sequence

from moex_carry.signal_engine.core.math_utils import price_to_ticks
from moex_carry.signal_engine.core.types import Candle


def true_range(current: Candle, previous_close: float) -> float:
    high_low = float(current.high) - float(current.low)
    high_close = abs(float(current.high) - float(previous_close))
    low_close = abs(float(current.low) - float(previous_close))
    return float(max(high_low, high_close, low_close))


def sma(values: Sequence[float], period: int) -> float | None:
    period_value = max(int(period), 1)
    if len(values) < period_value:
        return None
    window = values[-period_value:]
    return float(sum(window) / float(period_value))


def ema(values: Sequence[float], period: int) -> float | None:
    period_value = max(int(period), 1)
    if not values:
        return None
    alpha = 2.0 / float(period_value + 1)
    result = float(values[0])
    for value in values[1:]:
        result = alpha * float(value) + (1.0 - alpha) * result
    return float(result)


def atr_price(candles: Sequence[Candle], period: int = 14) -> float | None:
    if len(candles) < 2:
        return None
    tr_values: list[float] = []
    previous_close = float(candles[0].close)
    for candle in candles[1:]:
        tr_values.append(true_range(candle, previous_close))
        previous_close = float(candle.close)
    return sma(tr_values, max(int(period), 1))


def atr_ticks(candles: Sequence[Candle], tick_size: float, period: int = 14) -> int | None:
    atr = atr_price(candles, period=period)
    if atr is None:
        return None
    return max(price_to_ticks(atr, tick_size), 1)


def realized_volatility(closes: Sequence[float], window: int = 60) -> float | None:
    window_value = max(int(window), 1)
    if len(closes) < window_value + 1:
        return None
    returns_sq_sum = 0.0
    series = closes[-(window_value + 1) :]
    for idx in range(1, len(series)):
        prev = float(series[idx - 1])
        curr = float(series[idx])
        if prev <= 0 or curr <= 0:
            continue
        r = math.log(curr / prev)
        returns_sq_sum += r * r
    return float(math.sqrt(max(returns_sq_sum, 0.0)))


def relative_volume(volumes: Sequence[float], window: int = 60) -> float | None:
    window_value = max(int(window), 1)
    if len(volumes) < window_value + 1:
        return None
    baseline = sum(float(value) for value in volumes[-(window_value + 1) : -1]) / float(window_value)
    if baseline <= 0:
        return None
    return float(float(volumes[-1]) / baseline)
