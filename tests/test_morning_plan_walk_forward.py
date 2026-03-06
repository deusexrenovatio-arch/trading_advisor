from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from moex_carry.signal_engine.core.calendar import MarketCalendar, TimeWindow
from moex_carry.signal_engine.core.types import Candle, Level, OrderIntent, OrderType, Setup, Side, TF


def _load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_morning_plan_walk_forward.py"
    spec = importlib.util.spec_from_file_location("morning_walk_forward_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _calendar() -> MarketCalendar:
    return MarketCalendar(
        tz_name="Europe/Moscow",
        sessions=[TimeWindow(start=time(10, 0), end=time(23, 50))],
        clearing=[],
        forbid_margin_min=0,
    )


def test_simulate_setup_stop_limit_same_bar_tp_sl_is_worst_case_sl():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 10, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S1",
        side=Side.BUY,
        entry_level=Level(tf=TF.H1, kind="BOX_H", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.STOP_LIMIT,
            side=Side.BUY,
            price_ticks=100,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=15),
            meta={"limit_price_ticks": 101, "setup_kind": "BOX_BREAKOUT"},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=105,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=6,
    )
    bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=99.0, high=102.0, low=100.0, close=101.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=101.0, high=106.0, low=94.0, close=95.0, volume=20.0),
    ]
    result = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
    )
    assert result.filled is True
    assert result.outcome == "SL"
    assert result.entry_ticks == 101
    assert result.exit_ticks == 95
    assert result.gross_ticks == -6.0


def test_simulate_setup_stop_limit_fallback_to_market_increases_fill_rate():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 10, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S1F",
        side=Side.BUY,
        entry_level=Level(tf=TF.H1, kind="BOX_H", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.STOP_LIMIT,
            side=Side.BUY,
            price_ticks=100,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=20),
            meta={
                "limit_price_ticks": 99,
                "setup_kind": "BOX_BREAKOUT",
                "stop_limit_fallback_to_market_min": 5,
                "stop_limit_fallback_slip_ticks": 1,
            },
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=94,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=108,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=6,
    )
    bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=99.0, high=101.0, low=100.0, close=100.5, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=100.5, high=102.0, low=100.0, close=101.5, volume=15.0),
        Candle(ts=as_of + timedelta(minutes=15), open=101.5, high=109.0, low=101.0, close=108.0, volume=20.0),
    ]
    result = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
    )
    assert result.filled is True
    assert result.entry_ticks == 101


def test_simulate_setup_limit_no_fill_until_expiry():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 10, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S2",
        side=Side.BUY,
        entry_level=Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=10),
            meta={"setup_kind": "PULLBACK_LIMIT"},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=110,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=104.0, high=106.0, low=103.0, close=105.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=103.0, high=105.0, low=102.0, close=104.0, volume=15.0),
    ]
    result = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.5, slippage_ticks_per_side=1.0, spread_half_ticks=1.0),
    )
    assert result.filled is False
    assert result.outcome == "NO_FILL"
    assert result.net_ticks == 0.0


def test_simulate_setup_limit_uses_entry_range_fill_price():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 10, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S2R",
        side=Side.BUY,
        entry_level=Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            price_range_low_ticks=99,
            price_range_high_ticks=101,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=10),
            meta={"setup_kind": "PULLBACK_LIMIT"},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=110,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=104.0, high=106.0, low=101.0, close=105.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=103.0, high=105.0, low=102.0, close=104.0, volume=15.0),
    ]
    result = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
    )
    assert result.filled is True
    assert result.entry_ticks == 101


def test_simulate_setup_limit_entry_improve_ticks_waits_for_better_price():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 10, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S2RI",
        side=Side.BUY,
        entry_level=Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            price_range_low_ticks=99,
            price_range_high_ticks=101,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=15),
            meta={"setup_kind": "PULLBACK_LIMIT"},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=110,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=104.0, high=106.0, low=100.0, close=105.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=103.0, high=104.0, low=99.0, close=100.0, volume=12.0),
        Candle(ts=as_of + timedelta(minutes=15), open=100.0, high=101.0, low=99.0, close=100.0, volume=14.0),
    ]
    baseline = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
    )
    improved = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
        limit_entry_improve_ticks=2,
    )
    assert baseline.filled is True
    assert baseline.entry_ticks == 101
    assert improved.filled is True
    assert improved.entry_ticks == 99
    assert improved.entry_ts != baseline.entry_ts


def test_simulate_setup_limit_fallback_to_market_fills_after_timeout():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 10, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S2LF",
        side=Side.BUY,
        entry_level=Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            price_range_low_ticks=99,
            price_range_high_ticks=101,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=20),
            meta={"setup_kind": "PULLBACK_LIMIT"},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=110,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=104.0, high=106.0, low=103.0, close=105.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=105.0, high=106.0, low=103.0, close=104.0, volume=12.0),
        Candle(ts=as_of + timedelta(minutes=15), open=104.0, high=105.0, low=103.0, close=104.0, volume=14.0),
    ]
    baseline = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
    )
    fallback = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
        limit_fallback_to_market_minutes=10,
        limit_fallback_slip_ticks=1,
    )
    assert baseline.filled is False
    assert baseline.outcome == "NO_FILL"
    assert fallback.filled is True
    assert fallback.entry_ticks == 102
    assert fallback.entry_ts == (as_of + timedelta(minutes=15)).isoformat()


def test_simulate_setup_respects_time_stop_minutes_from_setup_meta():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 10, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S2TS",
        side=Side.BUY,
        entry_level=Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=20),
            meta={"setup_kind": "PULLBACK_LIMIT", "time_stop_minutes": 10},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=110,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=101.0, high=102.0, low=99.0, close=100.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=100.0, high=103.0, low=99.0, close=101.0, volume=12.0),
        Candle(ts=as_of + timedelta(minutes=15), open=101.0, high=103.0, low=100.0, close=102.0, volume=14.0),
    ]
    result = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
    )
    assert result.filled is True
    assert result.outcome == "EXIT"
    assert result.exit_ticks == 102


def test_simulate_setup_break_even_arm_moves_stop_to_entry():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 10, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S2BE",
        side=Side.BUY,
        entry_level=Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=30),
            meta={"setup_kind": "PULLBACK_LIMIT"},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=110,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=100.5, high=101.0, low=99.0, close=100.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=100.0, high=103.0, low=101.0, close=102.0, volume=12.0),
        Candle(ts=as_of + timedelta(minutes=15), open=102.0, high=101.0, low=100.0, close=100.5, volume=14.0),
        Candle(ts=as_of + timedelta(minutes=20), open=100.5, high=101.0, low=99.5, close=100.0, volume=16.0),
    ]
    no_be = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
    )
    with_be = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
        break_even_rr=0.5,
        break_even_buffer_ticks=0,
    )
    assert no_be.outcome == "EXIT"
    assert with_be.outcome == "SL"
    assert with_be.exit_ticks == 100
    assert with_be.gross_ticks == 0.0


def test_simulate_setup_same_bar_policy_tp_first_changes_collision_outcome():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 10, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S2SBP",
        side=Side.BUY,
        entry_level=Level(tf=TF.H1, kind="BOX_H", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.STOP_LIMIT,
            side=Side.BUY,
            price_ticks=100,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=15),
            meta={"limit_price_ticks": 101, "setup_kind": "BOX_BREAKOUT"},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=105,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=6,
    )
    bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=99.0, high=102.0, low=100.0, close=101.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=101.0, high=106.0, low=94.0, close=105.0, volume=20.0),
    ]
    default_result = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
    )
    tp_first_result = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
        same_bar_policy="tp_first",
    )
    assert default_result.outcome == "SL"
    assert tp_first_result.outcome == "TP"
    assert tp_first_result.exit_ticks == 105


def test_simulate_setup_tp_rr_and_sl_rr_override_bracket_distances():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 10, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S2RR",
        side=Side.BUY,
        entry_level=Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=30),
            meta={"setup_kind": "PULLBACK_LIMIT"},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=120,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    tp_bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=100.0, high=101.0, low=99.0, close=100.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=100.0, high=103.0, low=100.0, close=102.0, volume=12.0),
        Candle(ts=as_of + timedelta(minutes=15), open=102.0, high=102.0, low=101.0, close=101.0, volume=14.0),
    ]
    baseline_tp = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=tp_bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
    )
    tp_rr_result = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=tp_bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
        tp_rr=0.6,
    )
    assert baseline_tp.outcome == "EXIT"
    assert tp_rr_result.outcome == "TP"
    assert tp_rr_result.exit_ticks == 103

    sl_bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=100.0, high=101.0, low=99.0, close=100.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=100.0, high=101.0, low=97.0, close=98.5, volume=12.0),
        Candle(ts=as_of + timedelta(minutes=15), open=98.5, high=99.0, low=98.0, close=98.0, volume=14.0),
    ]
    baseline_sl = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=sl_bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
    )
    sl_rr_result = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=sl_bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
        sl_rr=0.4,
    )
    assert baseline_sl.outcome == "EXIT"
    assert sl_rr_result.outcome == "SL"
    assert sl_rr_result.exit_ticks == 98


def test_simulate_setup_max_profit_rr_caps_tp_distance():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 10, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S2CAP",
        side=Side.BUY,
        entry_level=Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=30),
            meta={"setup_kind": "PULLBACK_LIMIT"},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=120,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=100.0, high=101.0, low=99.0, close=100.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=100.0, high=108.0, low=100.0, close=106.0, volume=12.0),
        Candle(ts=as_of + timedelta(minutes=15), open=106.0, high=106.0, low=105.0, close=105.0, volume=14.0),
    ]
    baseline = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
    )
    capped = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
        max_profit_rr=1.0,
    )
    capped_ticks = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
        max_profit_ticks=2,
    )
    assert baseline.outcome == "EXIT"
    assert capped.outcome == "TP"
    assert capped.exit_ticks == 105
    assert capped_ticks.outcome == "TP"
    assert capped_ticks.exit_ticks == 102


def test_simulate_setup_trailing_and_global_max_holding_minutes():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 10, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S2TRAIL",
        side=Side.BUY,
        entry_level=Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=30),
            meta={"setup_kind": "PULLBACK_LIMIT"},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=120,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    trail_bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=100.0, high=101.0, low=99.0, close=100.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=100.0, high=106.0, low=100.0, close=105.0, volume=12.0),
        Candle(ts=as_of + timedelta(minutes=15), open=105.0, high=104.0, low=103.0, close=103.5, volume=14.0),
        Candle(ts=as_of + timedelta(minutes=20), open=103.5, high=103.5, low=102.0, close=102.0, volume=16.0),
    ]
    baseline_trail = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=trail_bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
    )
    trailing_result = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=trail_bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
        trail_activation_rr=1.0,
        trail_offset_ticks=2,
    )
    assert baseline_trail.outcome == "EXIT"
    assert trailing_result.outcome == "SL"
    assert trailing_result.exit_ticks == 104

    hold_bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=100.0, high=101.0, low=99.0, close=100.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=100.0, high=102.0, low=99.0, close=101.0, volume=12.0),
        Candle(ts=as_of + timedelta(minutes=15), open=101.0, high=102.0, low=100.0, close=101.5, volume=14.0),
        Candle(ts=as_of + timedelta(minutes=20), open=101.5, high=102.0, low=100.0, close=101.0, volume=16.0),
    ]
    no_hold_cap = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=hold_bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
    )
    with_hold_cap = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=hold_bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=mod.CostAssumptions(commission_ticks_per_side=0.0, slippage_ticks_per_side=0.0, spread_half_ticks=0.0),
        max_holding_minutes=10,
    )
    assert no_hold_cap.outcome == "EXIT"
    assert with_hold_cap.outcome == "EXIT"
    assert with_hold_cap.exit_ts != no_hold_cap.exit_ts


def test_simulate_setup_outcome_cost_multipliers_adjust_net_ticks():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 10, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S2COST",
        side=Side.BUY,
        entry_level=Level(tf=TF.D1, kind="PIVOT_PP", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=30),
            meta={"setup_kind": "PULLBACK_LIMIT"},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=106,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    costs = mod.CostAssumptions(commission_ticks_per_side=1.0, slippage_ticks_per_side=1.0, spread_half_ticks=0.0)
    tp_bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=100.0, high=101.0, low=99.0, close=100.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=100.0, high=106.0, low=100.0, close=105.0, volume=12.0),
    ]
    base_tp = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=tp_bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=costs,
    )
    discounted_tp = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=tp_bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=costs,
        tp_cost_mult=0.25,
    )
    assert base_tp.outcome == "TP"
    assert base_tp.cost_ticks == 4.0
    assert discounted_tp.cost_ticks == 1.0
    assert discounted_tp.net_ticks == pytest.approx(base_tp.net_ticks + 3.0)

    sl_bars = [
        Candle(ts=as_of + timedelta(minutes=5), open=100.0, high=101.0, low=99.0, close=100.0, volume=10.0),
        Candle(ts=as_of + timedelta(minutes=10), open=100.0, high=100.0, low=94.0, close=95.0, volume=12.0),
    ]
    base_sl = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=sl_bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=costs,
    )
    discounted_sl = mod._simulate_setup(
        instrument_id="BRH6",
        as_of_ts=as_of,
        setup=setup,
        m5_rows=sl_bars,
        tick_size=1.0,
        calendar=_calendar(),
        costs=costs,
        sl_cost_mult=0.5,
    )
    assert base_sl.outcome == "SL"
    assert base_sl.cost_ticks == 4.0
    assert discounted_sl.cost_ticks == 2.0
    assert discounted_sl.net_ticks == pytest.approx(base_sl.net_ticks + 2.0)


class _FakeIssClient:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls = 0

    def get_candles(self, *_args, **_kwargs):
        self.calls += 1
        return list(self.rows)


class _FakeSpecClient:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def get_futures_specs(self, _board: str):
        return list(self.rows)


def test_cached_fetch_second_call_uses_sqlite_without_network(tmp_path):
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    rows = [
        {"begin": "2026-02-20T10:00:00+03:00", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
        {"begin": "2026-02-20T10:01:00+03:00", "open": 10.5, "high": 11, "low": 10, "close": 10.8, "volume": 120},
    ]
    client = _FakeIssClient(rows)
    cache_db = tmp_path / "candles.sqlite"
    conn = mod._open_cache_db(cache_db)
    first = mod._fetch_candles_cached(
        conn=conn,
        client=client,
        engine="futures",
        market="forts",
        board="RFUD",
        secid="BRH6",
        date_from=date(2026, 2, 20),
        date_to=date(2026, 2, 20),
        interval=1,
        tz=tz,
        offline_only=False,
        refresh_cache=False,
        stats={"network_fetch_calls": 0, "network_rows": 0, "cache_rows_loaded": 0, "cache_rows_written": 0},
    )
    assert len(first) == 2
    assert client.calls == 1
    second = mod._fetch_candles_cached(
        conn=conn,
        client=client,
        engine="futures",
        market="forts",
        board="RFUD",
        secid="BRH6",
        date_from=date(2026, 2, 20),
        date_to=date(2026, 2, 20),
        interval=1,
        tz=tz,
        offline_only=True,
        refresh_cache=False,
        stats={"network_fetch_calls": 0, "network_rows": 0, "cache_rows_loaded": 0, "cache_rows_written": 0},
    )
    conn.close()
    assert len(second) == 2
    assert client.calls == 1


def test_cached_fetch_offline_mode_fails_on_cache_miss(tmp_path):
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    client = _FakeIssClient([])
    conn = mod._open_cache_db(tmp_path / "candles.sqlite")
    with pytest.raises(ValueError, match="cache_miss_offline_mode"):
        mod._fetch_candles_cached(
            conn=conn,
            client=client,
            engine="futures",
            market="forts",
            board="RFUD",
            secid="NGH6",
            date_from=date(2026, 2, 20),
            date_to=date(2026, 2, 20),
            interval=1,
            tz=tz,
            offline_only=True,
            refresh_cache=False,
            stats={"network_fetch_calls": 0, "network_rows": 0, "cache_rows_loaded": 0, "cache_rows_written": 0},
        )
    conn.close()


def test_summarize_includes_by_instrument_attribution():
    mod = _load_module()
    rows = [
        mod.SetupResult(
            instrument_id="BRH6",
            trade_date="2026-02-20",
            setup_id="S1",
            setup_kind="BOX_BREAKOUT",
            side="BUY",
            as_of_ts="2026-02-20T12:00:00+03:00",
            entry_ts="2026-02-20T12:05:00+03:00",
            exit_ts="2026-02-20T12:30:00+03:00",
            filled=True,
            outcome="TP",
            gross_ticks=15.0,
            net_ticks=10.0,
            cost_ticks=5.0,
            entry_ticks=100,
            exit_ticks=115,
        ),
        mod.SetupResult(
            instrument_id="BRH6",
            trade_date="2026-02-21",
            setup_id="S2",
            setup_kind="PULLBACK_LIMIT",
            side="BUY",
            as_of_ts="2026-02-21T12:00:00+03:00",
            entry_ts="2026-02-21T12:05:00+03:00",
            exit_ts="2026-02-21T12:20:00+03:00",
            filled=True,
            outcome="SL",
            gross_ticks=0.0,
            net_ticks=-5.0,
            cost_ticks=5.0,
            entry_ticks=100,
            exit_ticks=100,
        ),
        mod.SetupResult(
            instrument_id="NGH6",
            trade_date="2026-02-21",
            setup_id="S3",
            setup_kind="PULLBACK_LIMIT",
            side="SELL",
            as_of_ts="2026-02-21T12:00:00+03:00",
            entry_ts="2026-02-21T12:10:00+03:00",
            exit_ts="2026-02-21T13:00:00+03:00",
            filled=True,
            outcome="EXIT",
            gross_ticks=7.0,
            net_ticks=2.0,
            cost_ticks=5.0,
            entry_ticks=200,
            exit_ticks=193,
        ),
    ]
    summary = mod._summarize(rows, setups_total=4)
    assert summary["filled_trades"] == 3
    assert summary["fill_rate"] == pytest.approx(0.75)
    assert summary["by_instrument"]["BRH6"]["count"] == 2
    assert summary["by_instrument"]["BRH6"]["tp_rate"] == pytest.approx(0.5)
    assert summary["by_instrument"]["BRH6"]["sl_rate"] == pytest.approx(0.5)
    assert summary["by_instrument"]["BRH6"]["expectancy_net_ticks"] == pytest.approx(2.5)
    assert summary["by_instrument"]["NGH6"]["count"] == 1
    assert summary["by_instrument"]["NGH6"]["exit_rate"] == pytest.approx(1.0)


def test_train_selection_metrics_uses_median_minus_mad_penalty():
    mod = _load_module()
    summary = {
        "by_instrument": {
            "A": {"count": 5, "expectancy_net_ticks": 4.0},
            "B": {"count": 4, "expectancy_net_ticks": 2.0},
            "C": {"count": 1, "expectancy_net_ticks": 100.0},
        }
    }
    metrics = mod._train_selection_metrics(
        summary=summary,
        min_trades_per_instrument=3,
        mad_penalty=0.5,
    )
    assert metrics.instruments_with_trades == 3
    assert metrics.robust_instruments == 2
    assert metrics.median_expectancy == pytest.approx(3.0)
    assert metrics.mad_expectancy == pytest.approx(1.0)
    assert metrics.robust_score == pytest.approx(2.5)


def test_resolve_tuning_grid_profiles():
    mod = _load_module()
    baseline = mod._resolve_tuning_grid("baseline_v1")
    assert "execution.buffer_atr_mult" in baseline
    assert baseline["execution.buffer_atr_mult"] == [0.08, 0.10, 0.12]
    cost_aware = mod._resolve_tuning_grid("cost_aware_v2")
    assert "setups.min_rr_net" in cost_aware
    assert "setups.sl_atr_mult" in cost_aware
    with pytest.raises(ValueError, match="unknown_tuning_profile"):
        mod._resolve_tuning_grid("missing")


def test_resolve_tick_sizes_falls_back_to_group_step_for_expired_contract():
    mod = _load_module()
    client = _FakeSpecClient(
        [
            {"SECID": "BRH6", "MINSTEP": 0.01},
            {"SECID": "NGH6", "MINSTEP": 0.1},
        ]
    )
    tick_sizes = mod._resolve_tick_sizes(
        client=client,
        board="RFUD",
        instruments=["BRZ5", "NGH6", "UNKNOWN1"],
        explicit={},
    )
    assert tick_sizes["BRZ5"] == pytest.approx(0.01)
    assert tick_sizes["NGH6"] == pytest.approx(0.1)
    assert tick_sizes["UNKNOWN1"] == pytest.approx(0.01)


def test_resolve_search_space_profile_and_algorithm():
    mod = _load_module()
    space = mod._resolve_search_space("intraday_goal_v1")
    assert "setups.min_target_return_pct" in space
    space_v2 = mod._resolve_search_space("intraday_goal_v2")
    assert space_v2["setups.min_reward_gross_ticks"]["min"] == pytest.approx(12.0)
    assert space_v2["setups.min_target_return_pct"]["max"] == pytest.approx(1.0)
    space_v3 = mod._resolve_search_space("intraday_goal_v3")
    assert space_v3["regime.d1.adx_trend_min"]["min"] == 20
    assert space_v3["setups.require_vol_not_low"] == [True, False]
    assert "setups.stop_model" in space_v3
    assert "setups.entry_ttl_minutes" in space_v3
    space_v4 = mod._resolve_search_space("intraday_goal_precision_recall_v1")
    assert space_v4["setups.max_setups_per_instrument"]["max"] == 6
    assert space_v4["setups.enable_orb_breakout"] == [True, False]
    assert "setups.orb_opening_range_minutes" in space_v4
    assert "setups.enable_ema_pullback" in space_v4
    assert "setups.enable_vwap_pullback" in space_v4
    assert "setups.enable_volatility_compression_breakout" in space_v4
    assert "setups.vol_comp_max_recent_to_prev_ratio" in space_v4
    assert "setups.time_stop_minutes" in space_v4
    assert mod._resolve_search_algorithm("grid") == "GRID"
    assert mod._resolve_search_algorithm("tpe") == "TPE"
    with pytest.raises(ValueError, match="unknown_search_space_profile"):
        mod._resolve_search_space("missing")
    with pytest.raises(ValueError, match="unknown_search_space_profile"):
        mod._resolve_search_space("intraday_goal_v4_clustered")
    with pytest.raises(ValueError, match="unknown_search_algorithm"):
        mod._resolve_search_algorithm("bad")


def test_front_selector_rolls_to_next_contract_before_expiry_cutoff():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    payload = {
        ("BRZ5", TF.M5): [
            Candle(ts=datetime(2025, 9, 1, 10, 0, tzinfo=tz), open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0),
            Candle(ts=datetime(2025, 12, 20, 10, 0, tzinfo=tz), open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0),
        ],
        ("BRH6", TF.M5): [
            Candle(ts=datetime(2025, 12, 10, 10, 0, tzinfo=tz), open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0),
            Candle(ts=datetime(2026, 3, 20, 10, 0, tzinfo=tz), open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0),
        ],
        ("NGH6", TF.M5): [
            Candle(ts=datetime(2025, 12, 10, 10, 0, tzinfo=tz), open=50.0, high=51.0, low=49.0, close=50.0, volume=1.0),
            Candle(ts=datetime(2026, 3, 20, 10, 0, tzinfo=tz), open=50.0, high=51.0, low=49.0, close=50.0, volume=1.0),
        ],
    }
    selector = mod._build_front_selector(
        instruments=["BRZ5", "BRH6", "NGH6"],
        payload=payload,
        roll_avoid_expiry_days=3,
    )
    assert selector.reporting_ids == ["BR", "NG"]
    on_early_day = dict(selector.resolve_day(date(2025, 12, 15)))
    on_roll_day = dict(selector.resolve_day(date(2025, 12, 19)))
    assert on_early_day["BR"] == "BRZ5"
    assert on_roll_day["BR"] == "BRH6"
    assert on_roll_day["NG"] == "NGH6"


def test_resolve_cost_model_profile():
    mod = _load_module()
    assert mod._resolve_cost_model_profile("fixed_v1") == "fixed_v1"
    assert mod._resolve_cost_model_profile("train_proxy_v1") == "train_proxy_v1"
    assert mod._resolve_cost_model_profile("train_proxy_regime_v1") == "train_proxy_regime_v1"
    with pytest.raises(ValueError, match="unknown_cost_model_profile"):
        mod._resolve_cost_model_profile("missing")


def test_derive_fold_instrument_costs_train_proxy_changes_by_instrument():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    start = datetime(2026, 2, 1, 10, 0, tzinfo=tz)
    bars_a = [
        Candle(ts=start + timedelta(minutes=5 * idx), open=100.0, high=101.0, low=99.0, close=100.0, volume=5000.0)
        for idx in range(20)
    ]
    bars_b = [
        Candle(ts=start + timedelta(minutes=5 * idx), open=100.0, high=112.0, low=88.0, close=100.0, volume=200.0)
        for idx in range(20)
    ]
    payload = {
        ("A", TF.M5): bars_a,
        ("B", TF.M5): bars_b,
    }
    base = mod.CostAssumptions(commission_ticks_per_side=0.5, slippage_ticks_per_side=1.0, spread_half_ticks=1.0)
    costs = mod._derive_fold_instrument_costs(
        instruments=["A", "B"],
        payload=payload,
        tick_sizes={"A": 1.0, "B": 1.0},
        train_start=date(2026, 2, 1),
        train_end=date(2026, 2, 2),
        base_costs=base,
        profile="train_proxy_v1",
    )
    assert set(costs.keys()) == {"A", "B"}
    assert costs["B"].round_trip_ticks > costs["A"].round_trip_ticks
    fixed = mod._derive_fold_instrument_costs(
        instruments=["A", "B"],
        payload=payload,
        tick_sizes={"A": 1.0, "B": 1.0},
        train_start=date(2026, 2, 1),
        train_end=date(2026, 2, 2),
        base_costs=base,
        profile="fixed_v1",
    )
    assert fixed["A"] == base
    assert fixed["B"] == base
    regime = mod._derive_fold_instrument_costs(
        instruments=["A", "B"],
        payload=payload,
        tick_sizes={"A": 1.0, "B": 1.0},
        train_start=date(2026, 2, 1),
        train_end=date(2026, 2, 2),
        base_costs=base,
        profile="train_proxy_regime_v1",
    )
    assert regime["B"].round_trip_ticks >= costs["B"].round_trip_ticks


def test_probability_helpers_dirichlet_prior_and_expected_return():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 20, 12, 0, tzinfo=tz)
    forecast = mod._probability_forecast(
        as_of_ts=as_of,
        context_key=("PULLBACK_LIMIT", "BR", "BUY"),
        history=[],
        dirichlet_alpha=1.0,
        half_life_days=30.0,
    )
    assert forecast["p_tp"] == pytest.approx(1 / 3)
    assert forecast["p_sl"] == pytest.approx(1 / 3)
    assert forecast["p_exit"] == pytest.approx(1 / 3)
    assert forecast["n_effective"] == pytest.approx(0.0)

    setup = Setup(
        setup_id="S1",
        side=Side.BUY,
        entry_level=Level(tf=TF.H1, kind="BOX_H", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(order_type=OrderType.LIMIT, side=Side.BUY, price_ticks=100, qty_lots=1, tif="DAY", meta={}),
        sl_order=OrderIntent(order_type=OrderType.STOP, side=Side.SELL, price_ticks=95, qty_lots=1, tif="GTC", meta={}),
        tp_order=OrderIntent(order_type=OrderType.LIMIT, side=Side.SELL, price_ticks=110, qty_lots=1, tif="GTC", meta={}),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    costs = mod.CostAssumptions(commission_ticks_per_side=0.5, slippage_ticks_per_side=1.0, spread_half_ticks=1.0)
    expected = mod._expected_return_from_forecast(setup=setup, costs=costs, forecast=forecast)
    assert expected == pytest.approx(-3.3333333333)


def test_goal_adjusted_selection_score_penalizes_out_of_band_trade_frequency():
    mod = _load_module()
    goal = mod.GoalConstraints(min_trades_per_week=2.0, max_trades_per_week=4.0, trade_freq_penalty=3.0)
    in_band = mod._goal_adjusted_selection_score(
        base_score=10.0,
        summary={"filled_trades": 6},
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 14),
        goal=goal,
    )
    too_low = mod._goal_adjusted_selection_score(
        base_score=10.0,
        summary={"filled_trades": 1},
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 14),
        goal=goal,
    )
    too_high = mod._goal_adjusted_selection_score(
        base_score=10.0,
        summary={"filled_trades": 14},
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 14),
        goal=goal,
    )
    assert in_band == pytest.approx(10.0)
    assert too_low < in_band
    assert too_high < in_band


def test_goal_adjusted_selection_score_applies_extra_penalty():
    mod = _load_module()
    goal = mod.GoalConstraints(min_trades_per_week=1.0, max_trades_per_week=10.0, trade_freq_penalty=0.0)
    baseline = mod._goal_adjusted_selection_score(
        base_score=5.0,
        summary={"filled_trades": 3},
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 7),
        goal=goal,
        extra_penalty=0.0,
    )
    penalized = mod._goal_adjusted_selection_score(
        base_score=5.0,
        summary={"filled_trades": 3},
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 7),
        goal=goal,
        extra_penalty=1.25,
    )
    assert baseline == pytest.approx(5.0)
    assert penalized == pytest.approx(3.75)


def test_goal_adjusted_selection_score_applies_hard_constraints():
    mod = _load_module()
    goal = mod.GoalConstraints(
        min_trades_per_week=0.0,
        max_trades_per_week=99.0,
        trade_freq_penalty=0.0,
        hard_min_win_rate_net=0.75,
        hard_min_trades_per_week=2.0,
        hard_max_concentration_top_share=0.5,
        hard_violation_penalty=1000.0,
    )
    feasible = mod._goal_adjusted_selection_score(
        base_score=10.0,
        summary={
            "filled_trades": 10,
            "win_rate_net": 0.8,
            "by_instrument": {
                "A": {"net_ticks_sum": 40.0},
                "B": {"net_ticks_sum": 40.0},
            },
        },
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        goal=goal,
    )
    infeasible = mod._goal_adjusted_selection_score(
        base_score=10.0,
        summary={
            "filled_trades": 2,
            "win_rate_net": 0.45,
            "by_instrument": {
                "A": {"net_ticks_sum": 90.0},
                "B": {"net_ticks_sum": 10.0},
            },
        },
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        goal=goal,
    )
    assert feasible > -1000.0
    assert infeasible < feasible


def test_negative_subfold_metrics_counts_negative_periods():
    mod = _load_module()
    rows = [
        mod.SetupResult(
            instrument_id="BR",
            trade_date="2026-01-02",
            setup_id="S1",
            setup_kind="BOX_BREAKOUT",
            side="BUY",
            as_of_ts="2026-01-02T12:00:00+03:00",
            entry_ts="2026-01-02T12:05:00+03:00",
            exit_ts="2026-01-02T12:20:00+03:00",
            filled=True,
            outcome="SL",
            gross_ticks=-4.0,
            net_ticks=-9.0,
            cost_ticks=5.0,
            entry_ticks=100,
            exit_ticks=96,
        ),
        mod.SetupResult(
            instrument_id="BR",
            trade_date="2026-01-10",
            setup_id="S2",
            setup_kind="PULLBACK_LIMIT",
            side="BUY",
            as_of_ts="2026-01-10T12:00:00+03:00",
            entry_ts="2026-01-10T12:05:00+03:00",
            exit_ts="2026-01-10T12:20:00+03:00",
            filled=True,
            outcome="TP",
            gross_ticks=8.0,
            net_ticks=3.0,
            cost_ticks=5.0,
            entry_ticks=100,
            exit_ticks=108,
        ),
    ]
    metrics = mod._negative_subfold_metrics(
        results=rows,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 14),
        subfold_days=7,
        penalty_weight=2.0,
    )
    assert metrics["train_subfolds_with_trades"] == pytest.approx(2.0)
    assert metrics["train_negative_subfolds"] == pytest.approx(1.0)
    assert metrics["train_positive_subfolds"] == pytest.approx(1.0)
    assert metrics["train_negative_subfold_ratio"] == pytest.approx(0.5)
    assert metrics["negative_subfold_penalty"] == pytest.approx(2.0)


def test_tail_risk_metrics_and_acceptance_summary():
    mod = _load_module()
    rows = [
        mod.SetupResult(
            instrument_id="BR",
            trade_date="2026-01-02",
            setup_id="A",
            setup_kind="BOX_BREAKOUT",
            side="BUY",
            as_of_ts="2026-01-02T12:00:00+03:00",
            entry_ts="2026-01-02T12:05:00+03:00",
            exit_ts="2026-01-02T12:20:00+03:00",
            filled=True,
            outcome="SL",
            gross_ticks=-4.0,
            net_ticks=-9.0,
            cost_ticks=5.0,
            entry_ticks=100,
            exit_ticks=96,
        ),
        mod.SetupResult(
            instrument_id="BR",
            trade_date="2026-01-10",
            setup_id="B",
            setup_kind="BOX_BREAKOUT",
            side="BUY",
            as_of_ts="2026-01-10T12:00:00+03:00",
            entry_ts="2026-01-10T12:05:00+03:00",
            exit_ts="2026-01-10T12:20:00+03:00",
            filled=True,
            outcome="TP",
            gross_ticks=8.0,
            net_ticks=3.0,
            cost_ticks=5.0,
            entry_ticks=100,
            exit_ticks=108,
        ),
    ]
    tail = mod._tail_risk_metrics(
        results=rows,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 14),
        subfold_days=7,
        tail_alpha=0.5,
        lower_quantile=0.25,
    )
    assert tail["subfold_count"] == pytest.approx(2.0)
    assert tail["subfold_net_ticks_median"] == pytest.approx(-3.0)
    assert tail["subfold_net_ticks_cvar"] <= tail["subfold_net_ticks_median"]

    acceptance = mod._acceptance_summary(
        folds=[
            {"test_summary": {"net_ticks_sum": -4.0}},
            {"test_summary": {"net_ticks_sum": 6.0}},
        ],
        tail_alpha=0.5,
        max_negative_fold_share=0.6,
        min_median_fold_net_ticks=-1.0,
        min_tail_cvar_ticks=-10.0,
        holdout_summary={"net_ticks_sum": 1.0},
    )
    assert acceptance["passed"] is True


def test_acceptance_summary_applies_hard_goal_constraints():
    mod = _load_module()
    acceptance = mod._acceptance_summary(
        folds=[{"test_summary": {"net_ticks_sum": 2.0}}],
        tail_alpha=0.5,
        max_negative_fold_share=1.0,
        min_median_fold_net_ticks=-100.0,
        min_tail_cvar_ticks=-100.0,
        holdout_summary={"net_ticks_sum": 1.0},
        overall_summary={
            "filled_trades": 4,
            "win_rate_net": 0.5,
            "by_instrument": {
                "A": {"net_ticks_sum": 90.0},
                "B": {"net_ticks_sum": 10.0},
            },
        },
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        goal=mod.GoalConstraints(
            min_trades_per_week=0.0,
            max_trades_per_week=99.0,
            trade_freq_penalty=0.0,
            hard_min_win_rate_net=0.75,
            hard_min_trades_per_week=2.0,
            hard_max_concentration_top_share=0.5,
            hard_violation_penalty=1000.0,
        ),
    )
    assert acceptance["passed"] is False
    assert "hard_min_win_rate_net" in acceptance["failed_reasons"]
    assert "hard_min_trades_per_week" in acceptance["failed_reasons"]
    assert "hard_max_concentration_top_share" in acceptance["failed_reasons"]


def test_parse_cluster_roots_defaults_and_custom():
    mod = _load_module()
    defaults = mod._parse_cluster_roots([])
    assert defaults["BR"] == "energy"
    assert defaults["GD"] == "metals"
    custom = mod._parse_cluster_roots(["energy=BR,NG", "metals=GD,SV"])
    assert custom["BR"] == "energy"
    assert custom["SV"] == "metals"


def test_parse_decision_times_deduplicates_and_sorts():
    mod = _load_module()
    parsed = mod._parse_decision_times(["12:00,10:30", "10:30", "14:00"], "11:00")
    assert parsed == [time(10, 30), time(12, 0), time(14, 0)]
    fallback = mod._parse_decision_times([], "11:00")
    assert fallback == [time(11, 0)]


def test_fold_windows_support_embargo_and_purge():
    mod = _load_module()
    windows = mod._fold_windows(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 20),
        train_days=10,
        test_days=5,
        step_days=1,
        embargo_days=2,
        purge_days=1,
    )
    assert windows
    first = windows[0]
    assert first["train_end"] == date(2025, 12, 29)
    if len(windows) >= 2:
        assert windows[1]["test_start"] >= first["test_end"] + timedelta(days=2)


def test_normalized_selection_components_penalize_concentration():
    mod = _load_module()
    summary = {
        "by_instrument": {
            "A": {"count": 6, "expectancy_net_ticks": 8.0, "abs_gross_ticks_sum": 60.0, "net_ticks_sum": 48.0},
            "B": {"count": 6, "expectancy_net_ticks": 2.0, "abs_gross_ticks_sum": 60.0, "net_ticks_sum": 12.0},
            "C": {"count": 6, "expectancy_net_ticks": -1.0, "abs_gross_ticks_sum": 60.0, "net_ticks_sum": -6.0},
        }
    }
    scoring = mod.ObjectiveScoringConfig(
        concentration_penalty_weight=2.0,
        concentration_top_share_soft_cap=0.50,
        normalization_floor_ticks=1.0,
    )
    components = mod._normalized_selection_components(
        summary=summary,
        min_trades_per_instrument=3,
        mad_penalty=0.5,
        scoring=scoring,
    )
    assert components["normalized_instruments"] == 3
    assert components["normalized_robust_score"] > 0.0
    assert components["concentration_top_share"] == pytest.approx(0.8)
    assert components["concentration_penalty"] == pytest.approx(0.6)


def test_probability_context_key_modes():
    mod = _load_module()
    setup = Setup(
        setup_id="S1",
        side=Side.SELL,
        entry_level=Level(tf=TF.H1, kind="BOX_H", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(order_type=OrderType.LIMIT, side=Side.SELL, price_ticks=100, qty_lots=1, tif="DAY", meta={}),
        sl_order=OrderIntent(order_type=OrderType.STOP, side=Side.BUY, price_ticks=105, qty_lots=1, tif="GTC", meta={}),
        tp_order=OrderIntent(order_type=OrderType.LIMIT, side=Side.BUY, price_ticks=90, qty_lots=1, tif="GTC", meta={}),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    broad = mod._probability_context_key(setup=setup, instrument_id="BRH6", mode="setup_kind")
    narrow = mod._probability_context_key(setup=setup, instrument_id="BRH6", mode="setup_group_side")
    assert broad == ("UNKNOWN", "ALL", "ALL")
    assert narrow == ("UNKNOWN", "BR", "SELL")


def test_build_planned_signal_contains_entry_range_and_levels():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 21, 12, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S-PLAN",
        side=Side.BUY,
        entry_level=Level(tf=TF.H1, kind="BOX_H", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            price_range_low_ticks=99,
            price_range_high_ticks=101,
            qty_lots=1,
            tif="DAY",
            meta={"setup_kind": "PULLBACK_LIMIT", "target_return_pct": 0.7},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={"stop_model": "volatility"},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=110,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    planned = mod._build_planned_signal(
        instrument_id="BR",
        as_of_ts=as_of,
        setup=setup,
        gate_status="DISABLED",
        simulated=None,
    )
    assert planned.entry_range_low_ticks == 99
    assert planned.entry_range_high_ticks == 101
    assert planned.sl_ticks == 95
    assert planned.tp_ticks == 110
    assert planned.stop_model == "volatility"


def test_precision_filter_reason_blocks_by_side_and_risk():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 21, 12, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S-PRECISION",
        side=Side.BUY,
        entry_level=Level(tf=TF.H1, kind="BOX_H", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            qty_lots=1,
            tif="DAY",
            meta={"setup_kind": "PULLBACK_LIMIT", "target_return_pct": 0.7},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={"stop_model": "volatility"},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=110,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=5,
    )
    side_filter = mod.PrecisionFilterConfig(
        enabled=True,
        min_risk_ticks=None,
        min_target_return_pct=None,
        allowed_sides=("SELL",),
        allowed_setup_kinds=(),
        allowed_stop_models=(),
        allowed_decision_times=(),
        allowed_roots=(),
        allowed_instruments=(),
        dedup_setup_ids=False,
    )
    side_reason = mod._precision_filter_reason(
        instrument_id="BRH6",
        setup=setup,
        as_of_ts=as_of,
        precision_filter=side_filter,
    )
    assert side_reason == "precision_side"

    risk_filter = mod.PrecisionFilterConfig(
        enabled=True,
        min_risk_ticks=10,
        min_target_return_pct=None,
        allowed_sides=(),
        allowed_setup_kinds=(),
        allowed_stop_models=(),
        allowed_decision_times=(),
        allowed_roots=(),
        allowed_instruments=(),
        dedup_setup_ids=False,
    )
    risk_reason = mod._precision_filter_reason(
        instrument_id="BRH6",
        setup=setup,
        as_of_ts=as_of,
        precision_filter=risk_filter,
    )
    assert risk_reason == "precision_min_risk_ticks"


def test_binomial_wilson_lower_bound_behaves_as_lcb():
    mod = _load_module()
    lcb_low_conf = mod._binomial_wilson_lower_bound(wins=45, trials=60, confidence=0.8)
    lcb_high_conf = mod._binomial_wilson_lower_bound(wins=45, trials=60, confidence=0.95)
    raw = 45.0 / 60.0
    assert 0.0 <= lcb_low_conf <= raw
    assert 0.0 <= lcb_high_conf <= raw
    assert lcb_high_conf <= lcb_low_conf


def test_causal_first_components_add_instability_and_lcbs():
    mod = _load_module()
    rows = [
        mod.SetupResult(
            instrument_id="BRH6",
            trade_date="2026-01-02",
            setup_id="S1",
            setup_kind="ORB_BREAKOUT",
            side="BUY",
            as_of_ts="2026-01-02T10:30:00+03:00",
            entry_ts="2026-01-02T10:35:00+03:00",
            exit_ts="2026-01-02T11:00:00+03:00",
            filled=True,
            outcome="TP",
            gross_ticks=8.0,
            net_ticks=5.0,
            cost_ticks=3.0,
            entry_ticks=100,
            exit_ticks=105,
        ),
        mod.SetupResult(
            instrument_id="BRH6",
            trade_date="2026-01-09",
            setup_id="S2",
            setup_kind="ORB_BREAKOUT",
            side="BUY",
            as_of_ts="2026-01-09T10:30:00+03:00",
            entry_ts="2026-01-09T10:35:00+03:00",
            exit_ts="2026-01-09T11:00:00+03:00",
            filled=True,
            outcome="SL",
            gross_ticks=-9.0,
            net_ticks=-12.0,
            cost_ticks=3.0,
            entry_ticks=100,
            exit_ticks=88,
        ),
        mod.SetupResult(
            instrument_id="BRH6",
            trade_date="2026-01-16",
            setup_id="S3",
            setup_kind="ORB_BREAKOUT",
            side="BUY",
            as_of_ts="2026-01-16T10:30:00+03:00",
            entry_ts="2026-01-16T10:35:00+03:00",
            exit_ts="2026-01-16T11:00:00+03:00",
            filled=True,
            outcome="TP",
            gross_ticks=7.0,
            net_ticks=4.0,
            cost_ticks=3.0,
            entry_ticks=100,
            exit_ticks=104,
        ),
    ]
    summary = mod._summarize(rows, setups_total=3)
    period_start = date(2026, 1, 1)
    period_end = date(2026, 1, 21)
    metrics = mod._causal_first_components(
        results=rows,
        summary=summary,
        period_start=period_start,
        period_end=period_end,
        subfold_days=7,
        confidence=0.8,
    )
    raw_win_rate = float(summary["win_rate_net"])
    raw_tpw = mod._trades_per_week(
        filled_trades=int(summary["filled_trades"]),
        period_start=period_start,
        period_end=period_end,
    )
    assert metrics["causal_winrate_lcb"] <= raw_win_rate
    assert metrics["causal_trades_per_week_lcb"] <= raw_tpw
    assert metrics["causal_instability_expectancy_std"] > 0.0


def test_precision_filter_reason_blocks_by_root_and_instrument():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 2, 21, 12, 0, tzinfo=tz)
    setup = Setup(
        setup_id="S-PRECISION-ROOT",
        side=Side.BUY,
        entry_level=Level(tf=TF.H1, kind="BOX_H", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            qty_lots=1,
            tif="DAY",
            meta={"setup_kind": "ORB_BREAKOUT", "target_return_pct": 0.8},
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=95,
            qty_lots=1,
            tif="GTC",
            meta={"stop_model": "structure"},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=110,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=6,
    )

    root_filter = mod.PrecisionFilterConfig(
        enabled=True,
        min_risk_ticks=None,
        min_target_return_pct=None,
        allowed_sides=(),
        allowed_setup_kinds=(),
        allowed_stop_models=(),
        allowed_decision_times=(),
        allowed_roots=("BR",),
        allowed_instruments=(),
        dedup_setup_ids=False,
    )
    root_reason = mod._precision_filter_reason(
        instrument_id="NGH6",
        setup=setup,
        as_of_ts=as_of,
        precision_filter=root_filter,
    )
    assert root_reason == "precision_root"

    instrument_filter = mod.PrecisionFilterConfig(
        enabled=True,
        min_risk_ticks=None,
        min_target_return_pct=None,
        allowed_sides=(),
        allowed_setup_kinds=(),
        allowed_stop_models=(),
        allowed_decision_times=(),
        allowed_roots=(),
        allowed_instruments=("BRH6",),
        dedup_setup_ids=False,
    )
    instrument_reason = mod._precision_filter_reason(
        instrument_id="BRM6",
        setup=setup,
        as_of_ts=as_of,
        precision_filter=instrument_filter,
    )
    assert instrument_reason == "precision_instrument"


def test_evaluate_window_precision_filter_dedup_blocks_duplicate_setup_ids():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    payload = {("BRH6", TF.M5): []}
    eval_cache = mod._build_window_eval_cache(payload)
    calendar = _calendar()

    def _fake_compute_setups_cached(**kwargs):
        as_of = kwargs["as_of_ts"]
        return [
            Setup(
                setup_id="DUP-SETUP-1",
                side=Side.BUY,
                entry_level=Level(tf=TF.H1, kind="BOX_H", price_ticks=100, score=1.0, meta={}),
                entry_order=OrderIntent(
                    order_type=OrderType.LIMIT,
                    side=Side.BUY,
                    price_ticks=100,
                    qty_lots=1,
                    tif="DAY",
                    expire_ts=as_of + timedelta(minutes=30),
                    meta={"setup_kind": "PULLBACK_LIMIT", "target_return_pct": 1.0},
                ),
                sl_order=OrderIntent(
                    order_type=OrderType.STOP,
                    side=Side.SELL,
                    price_ticks=95,
                    qty_lots=1,
                    tif="GTC",
                    meta={"stop_model": "volatility"},
                ),
                tp_order=OrderIntent(
                    order_type=OrderType.LIMIT,
                    side=Side.SELL,
                    price_ticks=110,
                    qty_lots=1,
                    tif="GTC",
                    meta={},
                ),
                horizon="EOD",
                rationale=[],
                risk_ticks=5,
            )
        ]

    original_compute = mod._compute_setups_cached
    mod._compute_setups_cached = _fake_compute_setups_cached
    try:
        rows, summary, _history, planned_rows = mod._evaluate_window(
            period_start=date(2026, 2, 20),
            period_end=date(2026, 2, 20),
            instruments=["BRH6"],
            decision_times=[time(10, 30), time(12, 0)],
            tz=tz,
            cfg={},
            payload=payload,
            tick_sizes={"BRH6": 1.0},
            calendar=calendar,
            costs=mod.CostAssumptions(
                commission_ticks_per_side=0.0,
                slippage_ticks_per_side=0.0,
                spread_half_ticks=0.0,
            ),
            instrument_costs=None,
            front_selector=None,
            eval_cache=eval_cache,
            probability_gate=None,
            collect_history=False,
            precision_filter=mod.PrecisionFilterConfig(
                enabled=True,
                min_risk_ticks=None,
                min_target_return_pct=None,
                allowed_sides=(),
                allowed_setup_kinds=(),
                allowed_stop_models=(),
                allowed_decision_times=(),
                allowed_roots=(),
                allowed_instruments=(),
                dedup_setup_ids=True,
            ),
        )
    finally:
        mod._compute_setups_cached = original_compute

    assert len(rows) == 2
    assert len(planned_rows) == 2
    assert summary["setups_total"] == 2
    assert summary["gated_out"] == 1
    assert any(row.outcome == "GATED_OUT" and row.gate_reason == "precision_duplicate_setup_id" for row in rows)


def test_evaluate_window_collects_generator_rejection_trace_summary():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    payload = {("BRH6", TF.M5): []}
    eval_cache = mod._build_window_eval_cache(payload)
    calendar = _calendar()

    def _fake_compute_setups_cached(**kwargs):
        counts = kwargs.get("generator_rejection_trace_counts")
        if isinstance(counts, dict):
            key = "VWAP_PULLBACK_LIMIT:vwap_side_alignment_failed_buy"
            counts[key] = int(counts.get(key, 0)) + 2
        sample = kwargs.get("generator_rejection_trace_sample")
        if isinstance(sample, list):
            sample.append(
                {
                    "instrument_id": "BRH6",
                    "as_of_ts": kwargs["as_of_ts"].isoformat(),
                    "setup_kind": "VWAP_PULLBACK_LIMIT",
                    "rule": "vwap_side_alignment_failed_buy",
                }
            )
        return []

    original_compute = mod._compute_setups_cached
    mod._compute_setups_cached = _fake_compute_setups_cached
    try:
        rows, summary, _history, planned_rows = mod._evaluate_window(
            period_start=date(2026, 2, 20),
            period_end=date(2026, 2, 20),
            instruments=["BRH6"],
            decision_times=[time(10, 30)],
            tz=tz,
            cfg={},
            payload=payload,
            tick_sizes={"BRH6": 1.0},
            calendar=calendar,
            costs=mod.CostAssumptions(
                commission_ticks_per_side=0.0,
                slippage_ticks_per_side=0.0,
                spread_half_ticks=0.0,
            ),
            instrument_costs=None,
            front_selector=None,
            eval_cache=eval_cache,
            probability_gate=None,
            collect_history=False,
            precision_filter=mod.PrecisionFilterConfig(
                enabled=False,
                min_risk_ticks=None,
                min_target_return_pct=None,
                allowed_sides=(),
                allowed_setup_kinds=(),
                allowed_stop_models=(),
                allowed_decision_times=(),
                allowed_roots=(),
                allowed_instruments=(),
                dedup_setup_ids=False,
            ),
            collect_generator_rejection_trace=True,
            generator_rejection_trace_sample_limit=10,
        )
    finally:
        mod._compute_setups_cached = original_compute

    assert rows == []
    assert planned_rows == []
    trace = summary.get("generator_rejection_trace", {})
    assert int(trace.get("total", 0)) == 2
    counts = trace.get("counts", {})
    assert int(counts.get("VWAP_PULLBACK_LIMIT:vwap_side_alignment_failed_buy", 0)) == 2
    assert len(trace.get("sample", [])) == 1


def test_summarize_counts_gated_out_rows():
    mod = _load_module()
    rows = [
        mod.SetupResult(
            instrument_id="BRH6",
            trade_date="2026-02-20",
            setup_id="S1",
            setup_kind="BOX_BREAKOUT",
            side="BUY",
            as_of_ts="2026-02-20T12:00:00+03:00",
            entry_ts=None,
            exit_ts=None,
            filled=False,
            outcome="GATED_OUT",
            gross_ticks=0.0,
            net_ticks=0.0,
            cost_ticks=0.0,
            entry_ticks=None,
            exit_ticks=None,
            gate_status="BLOCK",
            gate_reason="low_n_effective",
        ),
        mod.SetupResult(
            instrument_id="BRH6",
            trade_date="2026-02-21",
            setup_id="S2",
            setup_kind="BOX_BREAKOUT",
            side="BUY",
            as_of_ts="2026-02-21T12:00:00+03:00",
            entry_ts="2026-02-21T12:05:00+03:00",
            exit_ts="2026-02-21T12:20:00+03:00",
            filled=True,
            outcome="TP",
            gross_ticks=15.0,
            net_ticks=10.0,
            cost_ticks=5.0,
            entry_ticks=100,
            exit_ticks=115,
        ),
    ]
    summary = mod._summarize(rows, setups_total=2)
    assert summary["gated_out"] == 1
    assert summary["filled_trades"] == 1


def test_should_probability_gate_fallback_by_fold_trade_floor():
    mod = _load_module()
    assert (
        mod._should_probability_gate_fallback(
            probability_gate_enabled=True,
            min_filled_trades_per_fold=2,
            test_summary={"filled_trades": 1},
        )
        is True
    )
    assert (
        mod._should_probability_gate_fallback(
            probability_gate_enabled=True,
            min_filled_trades_per_fold=2,
            test_summary={"filled_trades": 2},
        )
        is False
    )
    assert (
        mod._should_probability_gate_fallback(
            probability_gate_enabled=False,
            min_filled_trades_per_fold=2,
            test_summary={"filled_trades": 0},
        )
        is False
    )
    assert (
        mod._should_probability_gate_fallback(
            probability_gate_enabled=True,
            min_filled_trades_per_fold=0,
            test_summary={"filled_trades": 0},
        )
        is False
    )


def test_evaluate_window_fast_cache_keeps_parity_with_plain_evaluation():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    start = datetime(2026, 1, 1, 10, 0, tzinfo=tz)

    def _series(count: int, step: timedelta, slope: float) -> list[Candle]:
        rows: list[Candle] = []
        for idx in range(count):
            close = 100.0 + slope * idx
            rows.append(
                Candle(
                    ts=start + idx * step,
                    open=close - 0.2,
                    high=close + 0.6,
                    low=close - 0.6,
                    close=close,
                    volume=1_000.0 + idx,
                )
            )
        return rows

    payload = {
        ("BRH6", TF.D1): _series(90, timedelta(days=1), 0.7),
        ("BRH6", TF.H1): _series(350, timedelta(hours=1), 0.05),
        ("BRH6", TF.M5): _series(1500, timedelta(minutes=5), 0.01),
    }
    cfg = {
        "data": {"d1_limit": 90, "h1_limit": 300, "m5_limit": 500},
        "regime": {
            "d1": {
                "ema_fast": 20,
                "ema_slow": 50,
                "adx_period": 14,
                "er_period": 20,
                "dir_band_atr_mult": 0.25,
                "adx_trend_min": 25,
                "adx_range_max": 18,
                "er_trend_min": 0.30,
                "er_range_max": 0.20,
                "atr_period": 14,
                "atr_rank_lookback": 60,
                "vol_high_pct": 0.70,
                "vol_low_pct": 0.30,
            },
            "h1": {"ema_fast": 20, "ema_slow": 50, "atr_period": 14, "dir_band_atr_mult": 0.20},
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
            "require_vol_not_low": False,
            "pullback_max_dist_atr_mult": 1.0,
            "rr_default": 1.6,
            "min_target_ticks": 3,
            "max_risk_atr_mult": 1.2,
            "entry_expiry_policy": "SESSION_END",
        },
    }
    calendar = _calendar()
    costs = mod.CostAssumptions(commission_ticks_per_side=0.5, slippage_ticks_per_side=1.0, spread_half_ticks=1.0)
    kwargs = {
        "period_start": date(2026, 2, 2),
        "period_end": date(2026, 2, 5),
        "instruments": ["BRH6"],
        "decision_times": [time(12, 0)],
        "tz": tz,
        "cfg": cfg,
        "payload": payload,
        "tick_sizes": {"BRH6": 0.01},
        "calendar": calendar,
        "costs": costs,
        "instrument_costs": None,
        "front_selector": None,
        "probability_gate": None,
        "initial_history": None,
        "collect_history": True,
    }
    rows_plain, summary_plain, history_plain, planned_plain = mod._evaluate_window(**kwargs)
    cache = mod._build_window_eval_cache(payload)
    rows_fast, summary_fast, history_fast, planned_fast = mod._evaluate_window(**kwargs, eval_cache=cache)
    assert rows_plain == rows_fast
    assert summary_plain == summary_fast
    assert history_plain == history_fast
    assert planned_plain == planned_fast


def _make_expert_test_setup(*, as_of: datetime, risk_ticks: int, target_return_pct: float) -> Setup:
    return Setup(
        setup_id="EXPERT-S1",
        side=Side.BUY,
        entry_level=Level(tf=TF.H1, kind="BOX_H", price_ticks=100, score=1.0, meta={}),
        entry_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            price_ticks=100,
            qty_lots=1,
            tif="GTT",
            expire_ts=as_of + timedelta(minutes=30),
            meta={
                "setup_kind": "ORB_BREAKOUT",
                "target_return_pct": float(target_return_pct),
            },
        ),
        sl_order=OrderIntent(
            order_type=OrderType.STOP,
            side=Side.SELL,
            price_ticks=90,
            qty_lots=1,
            tif="GTC",
            meta={"stop_model": "structure"},
        ),
        tp_order=OrderIntent(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            price_ticks=120,
            qty_lots=1,
            tif="GTC",
            meta={},
        ),
        horizon="EOD",
        rationale=[],
        risk_ticks=int(risk_ticks),
    )


def test_expert_gate_reason_respects_rule_match_and_constraints():
    mod = _load_module()
    tz = ZoneInfo("Europe/Moscow")
    as_of = datetime(2026, 3, 5, 12, 0, tzinfo=tz)
    config = mod._parse_expert_gate_config(
        {
            "enabled": True,
            "default_action": "block",
            "rules": [
                {
                    "name": "energy_orb_midday",
                    "allow_setup_kinds": ["ORB_BREAKOUT"],
                    "allow_roots": ["BR", "NG"],
                    "allow_decision_times": ["12:00"],
                    "allow_clusters": ["energy"],
                    "min_risk_ticks": 100,
                    "min_target_return_pct": 0.6,
                }
            ],
        }
    )
    setup_ok = _make_expert_test_setup(as_of=as_of, risk_ticks=120, target_return_pct=0.8)
    reason_ok = mod._expert_filter_reason(
        instrument_id="BRH6",
        setup=setup_ok,
        as_of_ts=as_of,
        expert_gate=config,
        root_to_cluster={"BR": "energy", "NG": "energy"},
    )
    assert reason_ok is None

    setup_low_quality = _make_expert_test_setup(as_of=as_of, risk_ticks=90, target_return_pct=0.4)
    reason_constraints = mod._expert_filter_reason(
        instrument_id="BRH6",
        setup=setup_low_quality,
        as_of_ts=as_of,
        expert_gate=config,
        root_to_cluster={"BR": "energy", "NG": "energy"},
    )
    assert reason_constraints == "expert_rule_constraints"

    reason_no_match = mod._expert_filter_reason(
        instrument_id="SVC6",
        setup=setup_ok,
        as_of_ts=as_of,
        expert_gate=config,
        root_to_cluster={"BR": "energy", "NG": "energy"},
    )
    assert reason_no_match == "expert_no_match"


def test_parse_expert_gate_config_rejects_invalid_bounds():
    mod = _load_module()
    with pytest.raises(ValueError, match="expert_gate_rule_risk_bounds_invalid"):
        mod._parse_expert_gate_config(
            {
                "enabled": True,
                "rules": [{"name": "bad", "min_risk_ticks": 200, "max_risk_ticks": 100}],
            }
        )
