from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from moex_carry.signal_engine.core.calendar import MarketCalendar, TimeWindow
from moex_carry.signal_engine.core.types import Candle, Direction, LiquidityState, TrendState
from moex_carry.signal_engine.regime.engine import RegimeEngine


def _make_trend_candles(start: datetime, count: int, step: timedelta, slope: float) -> list[Candle]:
    rows: list[Candle] = []
    base = 100.0
    for idx in range(count):
        close = base + slope * idx
        rows.append(
            Candle(
                ts=start + idx * step,
                open=close - 0.3,
                high=close + 0.8,
                low=close - 0.8,
                close=close,
                volume=1_000.0 + idx,
            )
        )
    return rows


def _calendar() -> MarketCalendar:
    return MarketCalendar(
        tz_name="Europe/Moscow",
        sessions=[TimeWindow(start=datetime.min.time().replace(hour=0), end=datetime.min.time().replace(hour=23, minute=59))],
        clearing=[TimeWindow(start=datetime.min.time().replace(hour=14), end=datetime.min.time().replace(hour=14, minute=5))],
        forbid_margin_min=5,
    )


def test_regime_engine_detects_daily_trend_and_alignment():
    tz = ZoneInfo("Europe/Moscow")
    start = datetime(2025, 1, 1, tzinfo=tz)
    d1 = _make_trend_candles(start, 120, timedelta(days=1), slope=1.5)
    h1 = _make_trend_candles(start, 500, timedelta(hours=1), slope=0.08)
    m5 = _make_trend_candles(start, 900, timedelta(minutes=5), slope=0.01)
    engine = RegimeEngine(
        {
            "d1": {"ema_fast": 20, "ema_slow": 50, "adx_period": 14, "er_period": 20},
            "h1": {"ema_fast": 20, "ema_slow": 50, "atr_period": 14},
            "liquidity": {"spread_thin_ticks": 2, "spread_vacuum_ticks": 4, "depth_thin_lots": 50, "depth_vacuum_lots": 20},
        }
    )
    state = engine.compute(
        as_of_ts=d1[-1].ts,
        d1=d1,
        h1=h1,
        m5=m5,
        tick_size=0.01,
        orderbook={"bid": 200.00, "ask": 200.01, "depth_lots": 300},
        calendar=_calendar(),
    )
    assert state.daily_dir == Direction.UP
    assert state.daily_trend_state == TrendState.TREND
    assert state.h1_alignment is True
    assert state.liquidity_state == LiquidityState.OK
    assert state.daily_strength >= 0.0


def test_regime_engine_detects_neutral_band_and_non_alignment():
    tz = ZoneInfo("Europe/Moscow")
    start = datetime(2025, 1, 1, tzinfo=tz)
    d1 = _make_trend_candles(start, 120, timedelta(days=1), slope=0.0)
    h1 = _make_trend_candles(start, 500, timedelta(hours=1), slope=-0.05)
    m5 = _make_trend_candles(start, 900, timedelta(minutes=5), slope=0.0)
    engine = RegimeEngine(
        {
            "d1": {"ema_fast": 20, "ema_slow": 50, "adx_period": 14, "er_period": 20},
            "h1": {"ema_fast": 20, "ema_slow": 50, "atr_period": 14},
            "liquidity": {"spread_thin_ticks": 2, "spread_vacuum_ticks": 4, "depth_thin_lots": 50, "depth_vacuum_lots": 20},
        }
    )
    state = engine.compute(
        as_of_ts=d1[-1].ts,
        d1=d1,
        h1=h1,
        m5=m5,
        tick_size=0.01,
        orderbook=None,
        calendar=_calendar(),
    )
    assert state.daily_dir == Direction.NEUTRAL
    assert state.h1_alignment is False
    assert state.liquidity_state == LiquidityState.UNKNOWN
