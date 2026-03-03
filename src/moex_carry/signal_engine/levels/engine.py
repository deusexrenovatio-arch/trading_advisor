from __future__ import annotations

import math
from datetime import datetime

from moex_carry.signal_engine.core.calendar import MarketCalendar
from moex_carry.signal_engine.core.math_utils import price_to_ticks
from moex_carry.signal_engine.core.ohlcv import atr, ema
from moex_carry.signal_engine.core.types import Candle, Level, TF


class LevelEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}

    def compute_d1_levels(self, d1: list[Candle], tick_size: float) -> list[Level]:
        if tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        ordered = _ordered_if_needed(d1)
        if not ordered:
            return []
        prev = ordered[-2] if len(ordered) >= 2 else ordered[-1]

        levels: list[Level] = []
        levels.append(_level(TF.D1, "PDH", float(prev.high), tick_size, 0.95, prev.ts))
        levels.append(_level(TF.D1, "PDL", float(prev.low), tick_size, 0.95, prev.ts))
        levels.append(_level(TF.D1, "PDC", float(prev.close), tick_size, 0.90, prev.ts))

        d1_cfg = self.cfg.get("d1", {})
        if bool(d1_cfg.get("pivots", True)):
            pph = float(prev.high)
            ppl = float(prev.low)
            ppc = float(prev.close)
            pp = (pph + ppl + ppc) / 3.0
            r1 = (2.0 * pp) - ppl
            s1 = (2.0 * pp) - pph
            r2 = pp + (pph - ppl)
            s2 = pp - (pph - ppl)
            levels.extend(
                [
                    _level(TF.D1, "PIVOT_PP", pp, tick_size, 0.80, prev.ts),
                    _level(TF.D1, "PIVOT_R1", r1, tick_size, 0.80, prev.ts),
                    _level(TF.D1, "PIVOT_S1", s1, tick_size, 0.80, prev.ts),
                    _level(TF.D1, "PIVOT_R2", r2, tick_size, 0.70, prev.ts),
                    _level(TF.D1, "PIVOT_S2", s2, tick_size, 0.70, prev.ts),
                ]
            )

        donchian_period = int(d1_cfg.get("donchian_period", 20))
        if len(ordered) >= 1:
            sample = ordered[-max(donchian_period, 1) :]
            d20h = max(float(item.high) for item in sample)
            d20l = min(float(item.low) for item in sample)
            levels.append(
                Level(
                    tf=TF.D1,
                    kind=f"DONCHIAN_H_{donchian_period}",
                    price_ticks=price_to_ticks(d20h, tick_size),
                    score=0.85,
                    meta={"period": donchian_period, "bar_ts": sample[-1].ts.isoformat()},
                )
            )
            levels.append(
                Level(
                    tf=TF.D1,
                    kind=f"DONCHIAN_L_{donchian_period}",
                    price_ticks=price_to_ticks(d20l, tick_size),
                    score=0.85,
                    meta={"period": donchian_period, "bar_ts": sample[-1].ts.isoformat()},
                )
            )
        return levels

    def compute_h1_levels(self, h1: list[Candle], calendar: MarketCalendar, tick_size: float) -> list[Level]:
        del calendar
        if tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        ordered = _ordered_if_needed(h1)
        if not ordered:
            return []

        h1_cfg = self.cfg.get("h1", {})
        swing_k = max(int(h1_cfg.get("swing_k", 2)), 1)
        max_swings = max(int(h1_cfg.get("max_swings_each_side", 8)), 1)
        levels: list[Level] = []

        swing_highs: list[tuple[int, Candle]] = []
        swing_lows: list[tuple[int, Candle]] = []
        for idx in range(swing_k, len(ordered) - swing_k):
            if _is_swing_high(ordered, idx, swing_k):
                swing_highs.append((idx, ordered[idx]))
            if _is_swing_low(ordered, idx, swing_k):
                swing_lows.append((idx, ordered[idx]))

        swing_highs = swing_highs[-max_swings:]
        swing_lows = swing_lows[-max_swings:]
        for idx, candle in swing_highs:
            levels.append(
                Level(
                    tf=TF.H1,
                    kind="SWING_H",
                    price_ticks=price_to_ticks(float(candle.high), tick_size),
                    score=_swing_score(idx, len(ordered)),
                    meta={"k": swing_k, "bar_ts": candle.ts.isoformat()},
                )
            )
        for idx, candle in swing_lows:
            levels.append(
                Level(
                    tf=TF.H1,
                    kind="SWING_L",
                    price_ticks=price_to_ticks(float(candle.low), tick_size),
                    score=_swing_score(idx, len(ordered)),
                    meta={"k": swing_k, "bar_ts": candle.ts.isoformat()},
                )
            )

        box_hours = max(int(h1_cfg.get("box_hours", 6)), 2)
        atr_period = max(int(h1_cfg.get("atr_period", 14)), 1)
        box_range_mult = float(h1_cfg.get("box_range_atr_mult", 1.2))
        if len(ordered) >= box_hours:
            box_slice = ordered[-box_hours:]
            box_high = max(float(item.high) for item in box_slice)
            box_low = min(float(item.low) for item in box_slice)
            box_range = box_high - box_low
            atr_series = atr(ordered, atr_period)
            atr_last = _last_finite(atr_series)
            box_valid = atr_last > 0.0 and box_range <= box_range_mult * atr_last
            if box_valid:
                levels.append(
                    Level(
                        tf=TF.H1,
                        kind="BOX_H",
                        price_ticks=price_to_ticks(box_high, tick_size),
                        score=0.90,
                        meta={
                            "box_hours": box_hours,
                            "box_range": box_range,
                            "atr_h1": atr_last,
                            "bar_ts": box_slice[-1].ts.isoformat(),
                        },
                    )
                )
                levels.append(
                    Level(
                        tf=TF.H1,
                        kind="BOX_L",
                        price_ticks=price_to_ticks(box_low, tick_size),
                        score=0.90,
                        meta={
                            "box_hours": box_hours,
                            "box_range": box_range,
                            "atr_h1": atr_last,
                            "bar_ts": box_slice[-1].ts.isoformat(),
                        },
                    )
                )

        if bool(h1_cfg.get("include_ema20_level", True)):
            closes = [float(item.close) for item in ordered]
            ema20_series = ema(closes, 20)
            ema20_last = _last_finite(ema20_series)
            if ema20_last > 0.0:
                levels.append(
                    Level(
                        tf=TF.H1,
                        kind="EMA20_H1",
                        price_ticks=price_to_ticks(ema20_last, tick_size),
                        score=0.60,
                        meta={"period": 20, "bar_ts": ordered[-1].ts.isoformat()},
                    )
                )
        return levels

    def merge_and_rank(self, levels: list[Level]) -> list[Level]:
        if not levels:
            return []
        merge_distance_ticks = max(int(self.cfg.get("merge_distance_ticks", 2)), 0)
        ranked = sorted(
            levels,
            key=lambda item: (float(item.score), item.tf.value == TF.D1.value, -abs(int(item.price_ticks))),
            reverse=True,
        )
        merged: list[Level] = []
        for level in ranked:
            duplicate = None
            for existing in merged:
                if abs(int(level.price_ticks) - int(existing.price_ticks)) <= merge_distance_ticks:
                    duplicate = existing
                    break
            if duplicate is None:
                merged.append(level)
        return sorted(merged, key=lambda item: float(item.score), reverse=True)


def _is_swing_high(candles: list[Candle], idx: int, k: int) -> bool:
    current = float(candles[idx].high)
    for j in range(idx - k, idx + k + 1):
        if j == idx:
            continue
        if current <= float(candles[j].high):
            return False
    return True


def _is_swing_low(candles: list[Candle], idx: int, k: int) -> bool:
    current = float(candles[idx].low)
    for j in range(idx - k, idx + k + 1):
        if j == idx:
            continue
        if current >= float(candles[j].low):
            return False
    return True


def _swing_score(idx: int, total: int) -> float:
    age = max(total - 1 - idx, 0)
    half_life = max(total / 6.0, 1.0)
    score = 0.95 * math.exp(-math.log(2.0) * age / half_life)
    return float(max(min(score, 0.95), 0.55))


def _level(tf: TF, kind: str, price: float, tick_size: float, score: float, ts: datetime) -> Level:
    return Level(
        tf=tf,
        kind=kind,
        price_ticks=price_to_ticks(float(price), tick_size),
        score=float(score),
        meta={"bar_ts": ts.isoformat()},
    )


def _last_finite(values: list[float]) -> float:
    for value in reversed(values):
        if math.isfinite(value):
            return float(value)
    return 0.0


def _ordered_if_needed(rows: list[Candle]) -> list[Candle]:
    if len(rows) <= 1:
        return list(rows)
    for idx in range(1, len(rows)):
        if rows[idx - 1].ts > rows[idx].ts:
            return sorted(rows, key=lambda item: item.ts)
    return list(rows)
