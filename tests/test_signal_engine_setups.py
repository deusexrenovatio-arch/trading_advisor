from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from moex_carry.signal_engine.core.calendar import MarketCalendar, TimeWindow
from moex_carry.signal_engine.core.types import (
    Candle,
    Direction,
    ExecutionParams,
    Level,
    LiquidityState,
    OrderType,
    RegimeState,
    TF,
    TrendState,
    VolState,
)
from moex_carry.signal_engine.setups.generator import SetupGenerator


def _calendar() -> MarketCalendar:
    return MarketCalendar(
        tz_name="Europe/Moscow",
        sessions=[TimeWindow(start=time(10, 0), end=time(23, 50))],
        clearing=[TimeWindow(start=time(14, 0), end=time(14, 5)), TimeWindow(start=time(18, 50), end=time(19, 5))],
        forbid_margin_min=5,
    )


def _m5() -> list[Candle]:
    tz = ZoneInfo("Europe/Moscow")
    start = datetime(2026, 2, 10, 10, 0, tzinfo=tz)
    lows = [99, 98, 95, 98, 99, 100]
    highs = [101, 102, 100, 102, 103, 104]
    closes = [100, 100, 98, 101, 102, 100]
    rows: list[Candle] = []
    for idx in range(len(closes)):
        rows.append(
            Candle(
                ts=start + timedelta(minutes=idx * 5),
                open=closes[idx] - 0.2,
                high=float(highs[idx]),
                low=float(lows[idx]),
                close=float(closes[idx]),
                volume=1_000.0,
            )
        )
    return rows


def test_setup_generator_produces_trend_first_setups():
    tz = ZoneInfo("Europe/Moscow")
    as_of_ts = datetime(2026, 2, 10, 10, 45, tzinfo=tz)
    regime = RegimeState(
        as_of_ts=as_of_ts,
        daily_trend_state=TrendState.TREND,
        daily_dir=Direction.UP,
        daily_strength=0.8,
        daily_atr_ticks=40,
        daily_vol_state=VolState.NORMAL,
        h1_dir=Direction.UP,
        h1_alignment=True,
        h1_atr_ticks=20,
        liquidity_state=LiquidityState.OK,
        components={},
        warnings=[],
    )
    levels_d1 = [
        Level(tf=TF.D1, kind="PDC", price_ticks=100, score=0.9, meta={}),
        Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=99, score=0.8, meta={}),
        Level(tf=TF.D1, kind="PDH", price_ticks=108, score=0.95, meta={}),
        Level(tf=TF.D1, kind="PIVOT_R1", price_ticks=110, score=0.8, meta={}),
    ]
    levels_h1 = [
        Level(tf=TF.H1, kind="BOX_H", price_ticks=101, score=0.9, meta={}),
        Level(tf=TF.H1, kind="BOX_L", price_ticks=97, score=0.9, meta={}),
    ]
    exec_params = ExecutionParams(
        buffer_ticks=1,
        limit_slip_ticks=2,
        m5_atr_ticks=8,
        m5_noise_ratio=1.0,
        warnings=[],
    )
    generator = SetupGenerator(
        {
            "max_setups_per_instrument": 2,
            "entry_expiry_policy": "EOD_BEFORE_EVENING_CLEARING",
            "enable_cost_net_gate": False,
            "enable_eligibility_filter": False,
        }
    )
    setups = generator.generate(
        as_of_ts=as_of_ts,
        instrument_id="BRH6",
        last_price_ticks=102,
        regime=regime,
        levels_d1=levels_d1,
        levels_h1=levels_h1,
        exec_params=exec_params,
        calendar=_calendar(),
        m5=_m5(),
    )
    assert 0 < len(setups) <= 2
    first = setups[0]
    assert first.entry_order.order_type in {OrderType.STOP_LIMIT, OrderType.LIMIT}
    assert first.sl_order.order_type == OrderType.STOP
    assert first.tp_order.order_type == OrderType.LIMIT
    assert first.entry_order.expire_ts is not None


def test_setup_generator_blocks_when_regime_not_trend():
    tz = ZoneInfo("Europe/Moscow")
    as_of_ts = datetime(2026, 2, 10, 10, 45, tzinfo=tz)
    regime = RegimeState(
        as_of_ts=as_of_ts,
        daily_trend_state=TrendState.RANGE,
        daily_dir=Direction.NEUTRAL,
        daily_strength=0.1,
        daily_atr_ticks=20,
        daily_vol_state=VolState.NORMAL,
        h1_dir=Direction.NEUTRAL,
        h1_alignment=False,
        h1_atr_ticks=10,
        liquidity_state=LiquidityState.OK,
        components={},
        warnings=[],
    )
    generator = SetupGenerator({})
    setups = generator.generate(
        as_of_ts=as_of_ts,
        instrument_id="BRH6",
        last_price_ticks=100,
        regime=regime,
        levels_d1=[],
        levels_h1=[],
        exec_params=ExecutionParams(buffer_ticks=1, limit_slip_ticks=2, m5_atr_ticks=8, m5_noise_ratio=1.0, warnings=[]),
        calendar=_calendar(),
        m5=[],
    )
    assert setups == []


def test_setup_generator_cost_gate_blocks_low_net_reward():
    tz = ZoneInfo("Europe/Moscow")
    as_of_ts = datetime(2026, 2, 10, 10, 45, tzinfo=tz)
    regime = RegimeState(
        as_of_ts=as_of_ts,
        daily_trend_state=TrendState.TREND,
        daily_dir=Direction.UP,
        daily_strength=0.8,
        daily_atr_ticks=40,
        daily_vol_state=VolState.NORMAL,
        h1_dir=Direction.UP,
        h1_alignment=True,
        h1_atr_ticks=20,
        liquidity_state=LiquidityState.OK,
        components={},
        warnings=[],
    )
    levels_d1 = [
        Level(tf=TF.D1, kind="PDC", price_ticks=100, score=0.9, meta={}),
        Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=99, score=0.8, meta={}),
        Level(tf=TF.D1, kind="PDH", price_ticks=108, score=0.95, meta={}),
    ]
    levels_h1 = [
        Level(tf=TF.H1, kind="BOX_H", price_ticks=101, score=0.9, meta={}),
        Level(tf=TF.H1, kind="BOX_L", price_ticks=97, score=0.9, meta={}),
    ]
    exec_params = ExecutionParams(
        buffer_ticks=1,
        limit_slip_ticks=2,
        m5_atr_ticks=8,
        m5_noise_ratio=1.0,
        warnings=[],
    )
    generator = SetupGenerator(
        {
            "max_setups_per_instrument": 2,
            "estimated_round_trip_cost_ticks": 5.0,
            "min_reward_net_ticks": 2.0,
            "min_rr_net": 1.1,
            "min_reward_gross_ticks": 10.0,
            "entry_expiry_policy": "EOD_BEFORE_EVENING_CLEARING",
            "enable_eligibility_filter": False,
        }
    )
    setups = generator.generate(
        as_of_ts=as_of_ts,
        instrument_id="BRH6",
        last_price_ticks=102,
        regime=regime,
        levels_d1=levels_d1,
        levels_h1=levels_h1,
        exec_params=exec_params,
        calendar=_calendar(),
        m5=_m5(),
    )
    assert setups == []


def test_setup_generator_cost_gate_passes_large_reward():
    tz = ZoneInfo("Europe/Moscow")
    as_of_ts = datetime(2026, 2, 10, 10, 45, tzinfo=tz)
    regime = RegimeState(
        as_of_ts=as_of_ts,
        daily_trend_state=TrendState.TREND,
        daily_dir=Direction.UP,
        daily_strength=0.8,
        daily_atr_ticks=40,
        daily_vol_state=VolState.NORMAL,
        h1_dir=Direction.UP,
        h1_alignment=True,
        h1_atr_ticks=20,
        liquidity_state=LiquidityState.OK,
        components={},
        warnings=[],
    )
    levels_d1 = [
        Level(tf=TF.D1, kind="PDC", price_ticks=100, score=0.9, meta={}),
        Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=99, score=0.8, meta={}),
        Level(tf=TF.D1, kind="PIVOT_R2", price_ticks=126, score=0.95, meta={}),
    ]
    levels_h1 = [
        Level(tf=TF.H1, kind="BOX_H", price_ticks=101, score=0.9, meta={}),
        Level(tf=TF.H1, kind="BOX_L", price_ticks=97, score=0.9, meta={}),
    ]
    exec_params = ExecutionParams(
        buffer_ticks=1,
        limit_slip_ticks=2,
        m5_atr_ticks=8,
        m5_noise_ratio=1.0,
        warnings=[],
    )
    generator = SetupGenerator(
        {
            "max_setups_per_instrument": 2,
            "estimated_round_trip_cost_ticks": 5.0,
            "min_reward_net_ticks": 2.0,
            "min_rr_net": 1.1,
            "min_reward_gross_ticks": 10.0,
            "entry_expiry_policy": "EOD_BEFORE_EVENING_CLEARING",
            "enable_eligibility_filter": False,
        }
    )
    setups = generator.generate(
        as_of_ts=as_of_ts,
        instrument_id="BRH6",
        last_price_ticks=102,
        regime=regime,
        levels_d1=levels_d1,
        levels_h1=levels_h1,
        exec_params=exec_params,
        calendar=_calendar(),
        m5=_m5(),
    )
    assert len(setups) >= 1
    cost_gate = setups[0].entry_order.meta.get("cost_gate")
    assert isinstance(cost_gate, dict)
    assert cost_gate.get("pass") is True


def test_setup_generator_eligibility_blocks_low_atr_vs_cost():
    tz = ZoneInfo("Europe/Moscow")
    as_of_ts = datetime(2026, 2, 10, 10, 45, tzinfo=tz)
    regime = RegimeState(
        as_of_ts=as_of_ts,
        daily_trend_state=TrendState.TREND,
        daily_dir=Direction.UP,
        daily_strength=0.8,
        daily_atr_ticks=40,
        daily_vol_state=VolState.NORMAL,
        h1_dir=Direction.UP,
        h1_alignment=True,
        h1_atr_ticks=20,
        liquidity_state=LiquidityState.OK,
        components={},
        warnings=[],
    )
    levels_d1 = [
        Level(tf=TF.D1, kind="PDC", price_ticks=100, score=0.9, meta={}),
        Level(tf=TF.D1, kind="PIVOT_R2", price_ticks=126, score=0.95, meta={}),
    ]
    levels_h1 = [
        Level(tf=TF.H1, kind="BOX_H", price_ticks=101, score=0.9, meta={}),
        Level(tf=TF.H1, kind="BOX_L", price_ticks=97, score=0.9, meta={}),
    ]
    exec_params = ExecutionParams(
        buffer_ticks=1,
        limit_slip_ticks=2,
        m5_atr_ticks=8,
        m5_noise_ratio=1.0,
        warnings=[],
    )
    generator = SetupGenerator(
        {
            "max_setups_per_instrument": 2,
            "estimated_round_trip_cost_ticks": 5.0,
            "enable_cost_net_gate": False,
            "enable_eligibility_filter": True,
            "min_atr_h1_cost_mult": 6.0,
            "min_atr_d1_cost_mult": 12.0,
        }
    )
    setups = generator.generate(
        as_of_ts=as_of_ts,
        instrument_id="BRH6",
        last_price_ticks=102,
        regime=regime,
        levels_d1=levels_d1,
        levels_h1=levels_h1,
        exec_params=exec_params,
        calendar=_calendar(),
        m5=_m5(),
    )
    assert setups == []


def test_setup_generator_eligibility_passes_when_atr_large():
    tz = ZoneInfo("Europe/Moscow")
    as_of_ts = datetime(2026, 2, 10, 10, 45, tzinfo=tz)
    regime = RegimeState(
        as_of_ts=as_of_ts,
        daily_trend_state=TrendState.TREND,
        daily_dir=Direction.UP,
        daily_strength=0.8,
        daily_atr_ticks=120,
        daily_vol_state=VolState.NORMAL,
        h1_dir=Direction.UP,
        h1_alignment=True,
        h1_atr_ticks=60,
        liquidity_state=LiquidityState.OK,
        components={},
        warnings=[],
    )
    levels_d1 = [
        Level(tf=TF.D1, kind="PDC", price_ticks=100, score=0.9, meta={}),
        Level(tf=TF.D1, kind="PIVOT_R2", price_ticks=126, score=0.95, meta={}),
    ]
    levels_h1 = [
        Level(tf=TF.H1, kind="BOX_H", price_ticks=101, score=0.9, meta={}),
        Level(tf=TF.H1, kind="BOX_L", price_ticks=97, score=0.9, meta={}),
    ]
    exec_params = ExecutionParams(
        buffer_ticks=1,
        limit_slip_ticks=2,
        m5_atr_ticks=8,
        m5_noise_ratio=1.0,
        warnings=[],
    )
    generator = SetupGenerator(
        {
            "max_setups_per_instrument": 2,
            "estimated_round_trip_cost_ticks": 5.0,
            "enable_cost_net_gate": False,
            "enable_eligibility_filter": True,
            "min_atr_h1_cost_mult": 6.0,
            "min_atr_d1_cost_mult": 12.0,
        }
    )
    setups = generator.generate(
        as_of_ts=as_of_ts,
        instrument_id="BRH6",
        last_price_ticks=102,
        regime=regime,
        levels_d1=levels_d1,
        levels_h1=levels_h1,
        exec_params=exec_params,
        calendar=_calendar(),
        m5=_m5(),
    )
    assert len(setups) >= 1
