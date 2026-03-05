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


def test_setup_generator_supports_volatility_stop_model():
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
        h1_atr_ticks=40,
        liquidity_state=LiquidityState.OK,
        components={},
        warnings=[],
    )
    levels_d1 = [
        Level(tf=TF.D1, kind="PDC", price_ticks=100, score=0.9, meta={}),
        Level(tf=TF.D1, kind="PIVOT_R2", price_ticks=140, score=0.95, meta={}),
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
            "stop_model": "volatility",
            "sl_atr_mult": 0.5,
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
    first = setups[0]
    expected_delta = 20  # 0.5 * h1_atr_ticks(40)
    assert abs(first.entry_order.price_ticks - first.sl_order.price_ticks) == expected_delta
    assert first.sl_order.meta.get("stop_model") in {"volatility", "volatility_fallback"}


def test_setup_generator_supports_volume_extreme_stop_model():
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
        Level(tf=TF.D1, kind="PIVOT_R2", price_ticks=140, score=0.95, meta={}),
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
    m5_rows = _m5()
    m5_rows[1] = Candle(
        ts=m5_rows[1].ts,
        open=m5_rows[1].open,
        high=m5_rows[1].high,
        low=96.0,
        close=m5_rows[1].close,
        volume=12_000.0,
    )
    generator = SetupGenerator(
        {
            "max_setups_per_instrument": 2,
            "entry_expiry_policy": "EOD_BEFORE_EVENING_CLEARING",
            "enable_cost_net_gate": False,
            "enable_eligibility_filter": False,
            "stop_model": "volume_extreme",
            "stop_lookback_bars": 6,
            "stop_volume_quantile": 0.70,
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
        m5=m5_rows,
    )
    assert len(setups) >= 1
    first = setups[0]
    assert first.sl_order.meta.get("stop_model") in {"volume_extreme", "volatility_fallback"}


def test_setup_generator_populates_entry_range_for_limit_setup():
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
        Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=99, score=0.8, meta={}),
        Level(tf=TF.D1, kind="PIVOT_R2", price_ticks=140, score=0.95, meta={}),
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
            "entry_range_half_width_ticks": 2,
        }
    )
    setups = generator.generate(
        as_of_ts=as_of_ts,
        instrument_id="BRH6",
        last_price_ticks=103,
        regime=regime,
        levels_d1=levels_d1,
        levels_h1=levels_h1,
        exec_params=exec_params,
        calendar=_calendar(),
        m5=_m5(),
    )
    limit_setups = [item for item in setups if item.entry_order.order_type == OrderType.LIMIT]
    assert len(limit_setups) >= 1
    item = limit_setups[0]
    assert item.entry_order.price_range_low_ticks == item.entry_order.price_ticks - 2
    assert item.entry_order.price_range_high_ticks == item.entry_order.price_ticks + 2


def test_setup_generator_supports_entry_ttl_and_stop_limit_fallback_meta():
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
        Level(tf=TF.D1, kind="PIVOT_R2", price_ticks=140, score=0.95, meta={}),
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
            "entry_expiry_policy": "SESSION_END",
            "entry_ttl_minutes": 30,
            "time_stop_minutes": 90,
            "stop_limit_fallback_to_market_min": 6,
            "stop_limit_fallback_slip_ticks": 2,
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
    stop_limit_setups = [item for item in setups if item.entry_order.order_type == OrderType.STOP_LIMIT]
    assert stop_limit_setups
    setup = stop_limit_setups[0]
    assert setup.entry_order.expire_ts is not None
    assert setup.entry_order.expire_ts <= as_of_ts + timedelta(minutes=30)
    assert setup.entry_order.meta.get("stop_limit_fallback_to_market_min") == 6
    assert setup.entry_order.meta.get("stop_limit_fallback_slip_ticks") == 2
    assert setup.entry_order.meta.get("time_stop_minutes") == 90


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


def test_setup_generator_blocks_when_target_return_pct_below_threshold():
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
        Level(tf=TF.D1, kind="PDH", price_ticks=104, score=0.95, meta={}),
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
            "enable_cost_net_gate": False,
            "enable_eligibility_filter": False,
            "min_target_return_pct": 15.0,
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


def test_setup_generator_supports_orb_breakout_family():
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
        Level(tf=TF.D1, kind="PDH", price_ticks=112, score=0.95, meta={}),
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
            "max_setups_per_instrument": 4,
            "enable_box_breakout": False,
            "enable_pullback_limit": False,
            "enable_orb_breakout": True,
            "enable_cost_net_gate": False,
            "enable_eligibility_filter": False,
            "orb_opening_range_minutes": 15,
            "orb_require_price_break": True,
        }
    )
    m5_rows = _m5()
    m5_rows[-1] = Candle(
        ts=m5_rows[-1].ts,
        open=105.8,
        high=106.5,
        low=104.0,
        close=106.0,
        volume=1_200.0,
    )
    setups = generator.generate(
        as_of_ts=as_of_ts,
        instrument_id="BRH6",
        last_price_ticks=106,
        regime=regime,
        levels_d1=levels_d1,
        levels_h1=levels_h1,
        exec_params=exec_params,
        calendar=_calendar(),
        m5=m5_rows,
    )
    assert len(setups) >= 1
    assert any(item.entry_order.meta.get("setup_kind") == "ORB_BREAKOUT" for item in setups)


def test_setup_generator_supports_ema_pullback_family():
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
        Level(tf=TF.D1, kind="PDH", price_ticks=112, score=0.95, meta={}),
    ]
    levels_h1 = [
        Level(tf=TF.H1, kind="EMA20_H1", price_ticks=100, score=0.7, meta={}),
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
            "max_setups_per_instrument": 4,
            "enable_box_breakout": False,
            "enable_pullback_limit": False,
            "enable_ema_pullback": True,
            "enable_cost_net_gate": False,
            "enable_eligibility_filter": False,
            "ema_pullback_max_dist_atr_mult": 1.5,
        }
    )
    setups = generator.generate(
        as_of_ts=as_of_ts,
        instrument_id="BRH6",
        last_price_ticks=103,
        regime=regime,
        levels_d1=levels_d1,
        levels_h1=levels_h1,
        exec_params=exec_params,
        calendar=_calendar(),
        m5=_m5(),
    )
    assert len(setups) >= 1
    assert any(item.entry_order.meta.get("setup_kind") == "EMA_PULLBACK_LIMIT" for item in setups)


def test_setup_generator_respects_enabled_setup_kinds_allowlist():
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
        Level(tf=TF.D1, kind="PDH", price_ticks=112, score=0.95, meta={}),
    ]
    levels_h1 = [
        Level(tf=TF.H1, kind="EMA20_H1", price_ticks=100, score=0.7, meta={}),
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
            "max_setups_per_instrument": 4,
            "enable_box_breakout": True,
            "enable_pullback_limit": True,
            "enable_orb_breakout": True,
            "enable_ema_pullback": True,
            "enabled_setup_kinds": ["EMA_PULLBACK_LIMIT"],
            "enable_cost_net_gate": False,
            "enable_eligibility_filter": False,
            "ema_pullback_max_dist_atr_mult": 1.5,
        }
    )
    setups = generator.generate(
        as_of_ts=as_of_ts,
        instrument_id="BRH6",
        last_price_ticks=103,
        regime=regime,
        levels_d1=levels_d1,
        levels_h1=levels_h1,
        exec_params=exec_params,
        calendar=_calendar(),
        m5=_m5(),
    )
    assert len(setups) >= 1
    assert {str(item.entry_order.meta.get("setup_kind")) for item in setups} == {"EMA_PULLBACK_LIMIT"}


def test_setup_generator_supports_vwap_pullback_family():
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
        Level(tf=TF.D1, kind="PDH", price_ticks=112, score=0.95, meta={}),
    ]
    levels_h1: list[Level] = []
    exec_params = ExecutionParams(
        buffer_ticks=1,
        limit_slip_ticks=2,
        m5_atr_ticks=8,
        m5_noise_ratio=1.0,
        warnings=[],
    )
    generator = SetupGenerator(
        {
            "max_setups_per_instrument": 4,
            "enable_box_breakout": False,
            "enable_pullback_limit": False,
            "enable_orb_breakout": False,
            "enable_ema_pullback": False,
            "enable_vwap_pullback": True,
            "enable_cost_net_gate": False,
            "enable_eligibility_filter": False,
            "vwap_pullback_max_dist_atr_mult": 1.5,
        }
    )
    setups = generator.generate(
        as_of_ts=as_of_ts,
        instrument_id="BRH6",
        last_price_ticks=103,
        regime=regime,
        levels_d1=levels_d1,
        levels_h1=levels_h1,
        exec_params=exec_params,
        calendar=_calendar(),
        m5=_m5(),
    )
    assert len(setups) >= 1
    assert any(item.entry_order.meta.get("setup_kind") == "VWAP_PULLBACK_LIMIT" for item in setups)


def test_setup_generator_supports_volatility_compression_breakout_family():
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
        h1_atr_ticks=40,
        liquidity_state=LiquidityState.OK,
        components={},
        warnings=[],
    )
    levels_d1 = [
        Level(tf=TF.D1, kind="PDC", price_ticks=100, score=0.9, meta={}),
        Level(tf=TF.D1, kind="PDH", price_ticks=124, score=0.95, meta={}),
    ]
    levels_h1: list[Level] = []
    exec_params = ExecutionParams(
        buffer_ticks=1,
        limit_slip_ticks=2,
        m5_atr_ticks=8,
        m5_noise_ratio=1.0,
        warnings=[],
    )
    start = datetime(2026, 2, 10, 10, 0, tzinfo=tz)
    m5_rows = [
        Candle(ts=start + timedelta(minutes=idx * 5), open=100.0, high=108.0, low=96.0, close=101.0, volume=1200.0)
        for idx in range(4)
    ]
    m5_rows.extend(
        [
            Candle(ts=start + timedelta(minutes=20), open=101.0, high=103.0, low=99.0, close=102.0, volume=900.0),
            Candle(ts=start + timedelta(minutes=25), open=102.0, high=103.0, low=100.0, close=102.0, volume=920.0),
            Candle(ts=start + timedelta(minutes=30), open=102.0, high=103.0, low=101.0, close=103.0, volume=940.0),
            Candle(ts=start + timedelta(minutes=35), open=103.0, high=109.0, low=102.0, close=109.0, volume=1300.0),
        ]
    )
    generator = SetupGenerator(
        {
            "max_setups_per_instrument": 4,
            "enable_box_breakout": False,
            "enable_pullback_limit": False,
            "enable_orb_breakout": False,
            "enable_ema_pullback": False,
            "enable_vwap_pullback": False,
            "enable_volatility_compression_breakout": True,
            "enable_cost_net_gate": False,
            "enable_eligibility_filter": False,
            "vol_comp_lookback_bars": 8,
            "vol_comp_recent_bars": 3,
            "vol_comp_max_recent_to_prev_ratio": 0.7,
            "vol_comp_min_range_atr_mult": 0.1,
            "vol_comp_max_range_atr_mult": 2.0,
        }
    )
    setups = generator.generate(
        as_of_ts=as_of_ts,
        instrument_id="BRH6",
        last_price_ticks=109,
        regime=regime,
        levels_d1=levels_d1,
        levels_h1=levels_h1,
        exec_params=exec_params,
        calendar=_calendar(),
        m5=m5_rows,
    )
    assert len(setups) >= 1
    assert any(item.entry_order.meta.get("setup_kind") == "VOLATILITY_COMPRESSION_BREAKOUT" for item in setups)


def test_setup_generator_records_rejection_trace_for_vwap_alignment_fail():
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
        Level(tf=TF.D1, kind="PDH", price_ticks=112, score=0.95, meta={}),
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
            "max_setups_per_instrument": 4,
            "enable_box_breakout": False,
            "enable_pullback_limit": False,
            "enable_orb_breakout": False,
            "enable_ema_pullback": False,
            "enable_vwap_pullback": True,
            "enable_cost_net_gate": False,
            "enable_eligibility_filter": False,
            "vwap_pullback_max_dist_atr_mult": 2.0,
            "vwap_require_side_alignment": True,
        }
    )
    start = datetime(2026, 2, 10, 10, 0, tzinfo=tz)
    m5_rows = [
        Candle(ts=start, open=109.0, high=111.0, low=108.0, close=110.0, volume=5_000.0),
        Candle(ts=start + timedelta(minutes=5), open=108.0, high=109.0, low=106.0, close=108.0, volume=4_000.0),
        Candle(ts=start + timedelta(minutes=10), open=91.0, high=92.0, low=89.0, close=90.0, volume=200.0),
    ]
    setups = generator.generate(
        as_of_ts=as_of_ts,
        instrument_id="BRH6",
        last_price_ticks=90,
        regime=regime,
        levels_d1=levels_d1,
        levels_h1=[],
        exec_params=exec_params,
        calendar=_calendar(),
        m5=m5_rows,
    )
    trace = generator.consume_rejection_trace()
    assert setups == []
    assert any(
        str(item.get("setup_kind")) == "VWAP_PULLBACK_LIMIT"
        and str(item.get("rule")) == "vwap_side_alignment_failed_buy"
        for item in trace
    )
