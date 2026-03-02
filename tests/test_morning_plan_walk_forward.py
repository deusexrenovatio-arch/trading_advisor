from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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
