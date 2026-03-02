from __future__ import annotations

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from moex_carry.signal_engine.core.calendar import MarketCalendar, TimeWindow
from moex_carry.signal_engine.core.types import Candle, TF
from moex_carry.signal_engine.data.candles import InMemoryCandleProvider
from moex_carry.signal_engine.plan.builder import MorningPlanBuilder


def _trend_series(start: datetime, count: int, step: timedelta, slope: float) -> list[Candle]:
    rows: list[Candle] = []
    for idx in range(count):
        close = 100.0 + slope * idx
        rows.append(
            Candle(
                ts=start + idx * step,
                open=close - 0.2,
                high=close + 0.7,
                low=close - 0.7,
                close=close,
                volume=1_000.0 + idx,
            )
        )
    return rows


def test_morning_plan_builder_is_deterministic():
    tz = ZoneInfo("Europe/Moscow")
    start = datetime(2026, 1, 1, 10, 0, tzinfo=tz)
    instrument = "BRH6"
    payload = {
        (instrument, TF.D1): _trend_series(start, 80, timedelta(days=1), slope=0.8),
        (instrument, TF.H1): _trend_series(start, 300, timedelta(hours=1), slope=0.05),
        (instrument, TF.M5): _trend_series(start, 1_000, timedelta(minutes=5), slope=0.005),
    }
    provider = InMemoryCandleProvider(payload)
    calendar = MarketCalendar(
        tz_name="Europe/Moscow",
        sessions=[TimeWindow(start=time(10, 0), end=time(23, 50))],
        clearing=[TimeWindow(start=time(14, 0), end=time(14, 5)), TimeWindow(start=time(18, 50), end=time(19, 5))],
        forbid_margin_min=5,
    )
    cfg = {
        "data": {"d1_limit": 80, "h1_limit": 300, "m5_limit": 1000},
        "regime": {
            "d1": {
                "ema_fast": 5,
                "ema_slow": 10,
                "adx_period": 5,
                "er_period": 5,
                "dir_band_atr_mult": 0.10,
                "adx_trend_min": 10,
                "adx_range_max": 8,
                "er_trend_min": 0.1,
                "er_range_max": 0.05,
                "atr_period": 5,
                "atr_rank_lookback": 20,
                "vol_high_pct": 0.7,
                "vol_low_pct": 0.3,
            },
            "h1": {"ema_fast": 5, "ema_slow": 10, "atr_period": 5, "dir_band_atr_mult": 0.1},
            "liquidity": {"spread_thin_ticks": 2, "spread_vacuum_ticks": 4, "depth_thin_lots": 50, "depth_vacuum_lots": 20},
        },
        "levels": {
            "merge_distance_ticks": 1,
            "d1": {"donchian_period": 20, "pivots": True},
            "h1": {"swing_k": 2, "max_swings_each_side": 8, "box_hours": 6, "box_range_atr_mult": 1.2, "include_ema20_level": True},
        },
        "execution": {
            "m5_atr_period": 14,
            "buffer_atr_mult": 0.10,
            "buffer_min_ticks": 1,
            "limit_slip_ticks": 2,
            "noise_warn_high": 2.5,
            "noise_warn_low": 0.4,
            "swing_k": 2,
        },
        "setups": {
            "max_setups_per_instrument": 2,
            "require_vol_not_low": True,
            "pullback_max_dist_atr_mult": 1.0,
            "rr_default": 1.6,
            "min_target_ticks": 3,
            "max_risk_atr_mult": 1.2,
            "entry_expiry_policy": "EOD_BEFORE_EVENING_CLEARING",
        },
    }
    builder = MorningPlanBuilder(provider, calendar, cfg)
    as_of_ts = payload[(instrument, TF.M5)][-1].ts
    plan_a = builder.build_plan(as_of_ts=as_of_ts, instrument_id=instrument, tick_size=0.01)
    plan_b = builder.build_plan(as_of_ts=as_of_ts, instrument_id=instrument, tick_size=0.01)

    assert plan_a == plan_b
    assert len(plan_a.levels) > 0
    assert len(plan_a.setups) <= 2
