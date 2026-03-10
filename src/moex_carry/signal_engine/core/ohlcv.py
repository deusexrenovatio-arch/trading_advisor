from __future__ import annotations

import math
from collections import OrderedDict
from datetime import datetime

from moex_carry.signal_engine.core.calendar import MarketCalendar
from moex_carry.signal_engine.core.types import Candle, TF


def resample_ohlcv(candles: list[Candle], target_tf: TF, calendar: MarketCalendar) -> list[Candle]:
    if not candles:
        return []
    ordered = sorted(candles, key=lambda item: item.ts)
    grouped: "OrderedDict[datetime, list[Candle]]" = OrderedDict()
    for candle in ordered:
        if not calendar.is_trading_time(candle.ts):
            continue
        bucket = _bucket_ts(candle.ts, target_tf=target_tf, calendar=calendar)
        grouped.setdefault(bucket, []).append(candle)

    output: list[Candle] = []
    for bucket, items in grouped.items():
        output.append(
            Candle(
                ts=bucket,
                open=float(items[0].open),
                high=float(max(float(item.high) for item in items)),
                low=float(min(float(item.low) for item in items)),
                close=float(items[-1].close),
                volume=float(sum(float(item.volume) for item in items)),
            )
        )
    return output


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    period_value = max(int(period), 1)
    alpha = 2.0 / float(period_value + 1)
    result = float(values[0])
    output: list[float] = []
    for value in values:
        result = alpha * float(value) + (1.0 - alpha) * result
        output.append(float(result))
    return output


def atr(candles: list[Candle], period: int) -> list[float]:
    period_value = max(int(period), 1)
    n = len(candles)
    if n == 0:
        return []
    if n == 1:
        return [float("nan")]

    tr: list[float] = [float("nan")]
    prev_close = float(candles[0].close)
    for candle in candles[1:]:
        high_low = float(candle.high) - float(candle.low)
        high_close = abs(float(candle.high) - float(prev_close))
        low_close = abs(float(candle.low) - float(prev_close))
        tr.append(float(max(high_low, high_close, low_close)))
        prev_close = float(candle.close)

    output: list[float] = [float("nan")] * n
    for idx in range(period_value, n):
        window = tr[idx - period_value + 1 : idx + 1]
        output[idx] = float(sum(window) / float(period_value))
    return output


def adx(candles: list[Candle], period: int) -> list[float]:
    period_value = max(int(period), 1)
    n = len(candles)
    if n == 0:
        return []
    if n < period_value + 1:
        return [float("nan")] * n

    tr = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for idx in range(1, n):
        curr = candles[idx]
        prev = candles[idx - 1]
        up_move = float(curr.high) - float(prev.high)
        down_move = float(prev.low) - float(curr.low)
        plus_dm[idx] = up_move if up_move > down_move and up_move > 0.0 else 0.0
        minus_dm[idx] = down_move if down_move > up_move and down_move > 0.0 else 0.0
        tr[idx] = float(
            max(
                float(curr.high) - float(curr.low),
                abs(float(curr.high) - float(prev.close)),
                abs(float(curr.low) - float(prev.close)),
            )
        )

    plus_di = [float("nan")] * n
    minus_di = [float("nan")] * n
    dx = [float("nan")] * n
    adx_values = [float("nan")] * n

    sm_tr = float(sum(tr[1 : period_value + 1]))
    sm_plus_dm = float(sum(plus_dm[1 : period_value + 1]))
    sm_minus_dm = float(sum(minus_dm[1 : period_value + 1]))
    if sm_tr > 0.0:
        plus_di[period_value] = 100.0 * sm_plus_dm / sm_tr
        minus_di[period_value] = 100.0 * sm_minus_dm / sm_tr
        di_sum = plus_di[period_value] + minus_di[period_value]
        dx[period_value] = (
            100.0 * abs(plus_di[period_value] - minus_di[period_value]) / di_sum
            if di_sum > 0.0
            else 0.0
        )

    for idx in range(period_value + 1, n):
        sm_tr = sm_tr - (sm_tr / period_value) + tr[idx]
        sm_plus_dm = sm_plus_dm - (sm_plus_dm / period_value) + plus_dm[idx]
        sm_minus_dm = sm_minus_dm - (sm_minus_dm / period_value) + minus_dm[idx]
        if sm_tr <= 0.0:
            plus_di[idx] = 0.0
            minus_di[idx] = 0.0
            dx[idx] = 0.0
            continue
        plus_di[idx] = 100.0 * sm_plus_dm / sm_tr
        minus_di[idx] = 100.0 * sm_minus_dm / sm_tr
        di_sum = plus_di[idx] + minus_di[idx]
        dx[idx] = 100.0 * abs(plus_di[idx] - minus_di[idx]) / di_sum if di_sum > 0.0 else 0.0

    first_adx_idx = 2 * period_value - 1
    if first_adx_idx < n:
        seed = [value for value in dx[period_value : first_adx_idx + 1] if math.isfinite(value)]
        if seed:
            adx_values[first_adx_idx] = float(sum(seed) / float(len(seed)))
        for idx in range(first_adx_idx + 1, n):
            prev = adx_values[idx - 1]
            cur_dx = dx[idx] if math.isfinite(dx[idx]) else 0.0
            adx_values[idx] = float(((prev * (period_value - 1)) + cur_dx) / float(period_value))
    return adx_values


def efficiency_ratio(closes: list[float], period: int) -> list[float]:
    period_value = max(int(period), 1)
    n = len(closes)
    if n == 0:
        return []
    output = [float("nan")] * n
    eps = 1e-12
    for idx in range(period_value, n):
        direction = abs(float(closes[idx]) - float(closes[idx - period_value]))
        volatility = 0.0
        for j in range(idx - period_value + 1, idx + 1):
            volatility += abs(float(closes[j]) - float(closes[j - 1]))
        output[idx] = float(direction / max(volatility, eps))
    return output


def percentile_rank(value: float, samples: list[float]) -> float:
    finite = [float(item) for item in samples if math.isfinite(float(item))]
    if not finite:
        return 0.5
    target = float(value)
    count = sum(1 for item in finite if item <= target)
    return float(count / float(len(finite)))


def _bucket_ts(ts: datetime, *, target_tf: TF, calendar: MarketCalendar) -> datetime:
    local = ts.astimezone(calendar.tz) if ts.tzinfo is not None else ts.replace(tzinfo=calendar.tz)
    if target_tf == TF.D1:
        return local.replace(hour=0, minute=0, second=0, microsecond=0)
    if target_tf == TF.H1:
        return local.replace(minute=0, second=0, microsecond=0)
    if target_tf == TF.M5:
        minute = (int(local.minute) // 5) * 5
        return local.replace(minute=minute, second=0, microsecond=0)
    raise ValueError(f"unsupported_target_tf:{target_tf}")
