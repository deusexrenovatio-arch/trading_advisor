from __future__ import annotations

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from moex_carry.signal_engine.core.calendar import MarketCalendar, TimeWindow
from moex_carry.signal_engine.core.math_utils import price_to_ticks
from moex_carry.signal_engine.core.types import Candle
from moex_carry.signal_engine.levels.engine import LevelEngine


def _calendar() -> MarketCalendar:
    return MarketCalendar(
        tz_name="Europe/Moscow",
        sessions=[TimeWindow(start=time(0, 0), end=time(23, 59))],
        clearing=[],
        forbid_margin_min=5,
    )


def test_level_engine_computes_pivots_and_donchian():
    tz = ZoneInfo("Europe/Moscow")
    start = datetime(2026, 1, 1, tzinfo=tz)
    d1 = [
        Candle(ts=start, open=95, high=105, low=85, close=100, volume=1000),
        Candle(ts=start + timedelta(days=1), open=100, high=110, low=90, close=100, volume=1000),
        Candle(ts=start + timedelta(days=2), open=101, high=111, low=91, close=102, volume=1000),
    ]
    engine = LevelEngine({"d1": {"donchian_period": 20, "pivots": True}})
    levels = engine.compute_d1_levels(d1, tick_size=1.0)
    by_kind = {item.kind: item for item in levels}
    assert by_kind["PDH"].price_ticks == 110
    assert by_kind["PDL"].price_ticks == 90
    assert by_kind["PDC"].price_ticks == 100
    assert by_kind["PIVOT_PP"].price_ticks == 100
    assert by_kind["PIVOT_R1"].price_ticks == 110
    assert by_kind["PIVOT_S1"].price_ticks == 90
    assert by_kind["PIVOT_R2"].price_ticks == 120
    assert by_kind["PIVOT_S2"].price_ticks == 80
    assert by_kind["DONCHIAN_H_20"].price_ticks == 111
    assert by_kind["DONCHIAN_L_20"].price_ticks == 85


def test_level_engine_detects_swings_and_h1_box():
    tz = ZoneInfo("Europe/Moscow")
    start = datetime(2026, 1, 1, tzinfo=tz)
    candles: list[Candle] = []
    highs = [100, 103, 108, 103, 100, 99, 102, 106, 102, 99, 98, 97, 102, 101, 100, 100.4, 100.5, 100.4, 100.5, 100.4]
    lows = [97, 98, 101, 99, 97, 95, 96, 100, 96, 95, 94, 93, 95, 96, 97, 99.8, 99.9, 99.8, 99.9, 99.8]
    closes = [99, 102, 106, 101, 99, 96, 101, 104, 100, 97, 95, 94, 101, 100, 99.8, 100.1, 100.2, 100.1, 100.2, 100.1]
    for idx, close in enumerate(closes):
        candles.append(
            Candle(
                ts=start + timedelta(hours=idx),
                open=close - 0.2,
                high=float(highs[idx]),
                low=float(lows[idx]),
                close=float(close),
                volume=1_000.0,
            )
        )
    engine = LevelEngine(
        {
            "h1": {
                "swing_k": 2,
                "max_swings_each_side": 8,
                "box_hours": 6,
                "box_range_atr_mult": 1.2,
                "include_ema20_level": True,
            }
        }
    )
    levels = engine.compute_h1_levels(candles, calendar=_calendar(), tick_size=0.1)
    kinds = {item.kind for item in levels}
    assert "SWING_H" in kinds
    assert "SWING_L" in kinds
    assert "BOX_H" in kinds
    assert "BOX_L" in kinds
    assert "EMA20_H1" in kinds
    box_h = next(item for item in levels if item.kind == "BOX_H")
    assert box_h.price_ticks == price_to_ticks(100.5, 0.1)
