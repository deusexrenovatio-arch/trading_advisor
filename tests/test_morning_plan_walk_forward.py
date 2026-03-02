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


class _FakeIssClient:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls = 0

    def get_candles(self, *_args, **_kwargs):
        self.calls += 1
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
