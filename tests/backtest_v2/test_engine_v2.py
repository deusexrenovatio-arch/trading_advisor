from datetime import date, timedelta

import pytest

from moex_carry.backtest_v2 import InMemoryDataStore, run_backtest_v2
from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.domain.models import KeyRate
from moex_carry.domain.portfolio import DailyInstrumentBar, PairSpec
from moex_carry.portfolio.contracts import RebalanceConfig


def _bar(secid: str, day: date, price: float, open_price: float | None = None) -> DailyInstrumentBar:
    return DailyInstrumentBar(
        secid=secid,
        date=day,
        open=open_price if open_price is not None else price,
        close=price,
        bid=price,
        ask=price,
        mid=price,
        last=price,
        volume=1000.0,
    )


def _make_request(start: date, end: date, *, equity: float = 1000.0) -> BacktestRequest:
    request = BacktestRequest()
    request.test.start_date = start
    request.test.end_date = end
    request.portfolio.account_equity = equity
    request.strategy.min_DTE_entry = 1
    request.strategy.close_buffer_days = 0
    request.strategy.H_max_days = 1
    request.strategy.w_floor = 1.0
    request.strategy.w_alpha = 0.0
    request.rates.r_cb_annual = 0.0
    request.rates.r_fund_annual = 0.0
    request.rates.r_disc_annual = 0.0
    request.execution.half_spread_bps = 0.0
    request.execution.slip_stock_bps = 0.0
    request.execution.slip_fut_bps = 0.0
    request.costs.fee_stock_bps = 0.0
    request.costs.fee_fut_per_contract = 0.0
    request.universe.max_pairs = 1
    return request


def _rebalance_config(min_score: float) -> RebalanceConfig:
    return RebalanceConfig(
        soft_rebalance_frequency="DAILY",
        hard_checks_frequency="DAILY",
        score_threshold_mode="ABSOLUTE",
        enter_total_score_min=min_score,
        keep_total_score_min=0.0,
        max_pairs_held=1,
        enter_min_DTE=1,
        close_buffer_days=0,
        TP_pct=0.5,
        SL_pct=0.5,
        h_max_days=1,
        exit_on_floor_fail=False,
        default_direction="cash_and_carry",
        max_contracts_per_pair=1,
    )


def test_backtest_v2_lookahead_protection():
    start = date(2025, 1, 1)
    end = date(2025, 1, 3)
    pair = PairSpec(stock_secid="AAA", future_secid="AAA_F", expiry=date(2025, 2, 1), multiplier=1.0)

    stock_bars = {
        start: [_bar("AAA", start, 100.0)],
        start + timedelta(days=1): [_bar("AAA", start + timedelta(days=1), 100.0)],
        start + timedelta(days=2): [_bar("AAA", start + timedelta(days=2), 100.0)],
    }
    fut_bars = {
        start: [_bar("AAA_F", start, 100.0)],
        start + timedelta(days=1): [_bar("AAA_F", start + timedelta(days=1), 110.0)],
        start + timedelta(days=2): [_bar("AAA_F", start + timedelta(days=2), 110.0)],
    }
    store = InMemoryDataStore(
        stock_bars=stock_bars,
        fut_bars=fut_bars,
        key_rates=[KeyRate(date=start, rate=0.0)],
    )
    request = _make_request(start, end)
    report = run_backtest_v2(
        request=request,
        universe=[pair],
        data_store=store,
        rebalance_config=_rebalance_config(0.5),
        fill_time="EOD",
        initial_equity=1000.0,
    )
    assert report.trades, "expected trade to close by day 3"
    assert report.trades[0].entry_date == start + timedelta(days=1)


def test_backtest_v2_next_open_executes_next_day_open():
    start = date(2025, 1, 1)
    end = date(2025, 1, 4)
    pair = PairSpec(stock_secid="AAA", future_secid="AAA_F", expiry=date(2025, 2, 1), multiplier=1.0)

    stock_bars = {
        start: [_bar("AAA", start, 100.0, open_price=100.0)],
        start + timedelta(days=1): [_bar("AAA", start + timedelta(days=1), 120.0, open_price=120.0)],
        start + timedelta(days=2): [_bar("AAA", start + timedelta(days=2), 120.0, open_price=120.0)],
        start + timedelta(days=3): [_bar("AAA", start + timedelta(days=3), 120.0, open_price=120.0)],
    }
    fut_bars = {
        start: [_bar("AAA_F", start, 110.0, open_price=110.0)],
        start + timedelta(days=1): [_bar("AAA_F", start + timedelta(days=1), 130.0, open_price=130.0)],
        start + timedelta(days=2): [_bar("AAA_F", start + timedelta(days=2), 130.0, open_price=130.0)],
        start + timedelta(days=3): [_bar("AAA_F", start + timedelta(days=3), 130.0, open_price=130.0)],
    }
    store = InMemoryDataStore(
        stock_bars=stock_bars,
        fut_bars=fut_bars,
        key_rates=[KeyRate(date=start, rate=0.0)],
    )
    request = _make_request(start, end)
    report = run_backtest_v2(
        request=request,
        universe=[pair],
        data_store=store,
        rebalance_config=_rebalance_config(0.1),
        fill_time="NEXT_OPEN",
        initial_equity=1000.0,
    )
    assert report.trades, "expected trade to close by day 3"
    trade = report.trades[0]
    assert trade.entry_date == start + timedelta(days=1)
    assert trade.entry_price_stock == pytest.approx(120.0)


def test_backtest_v2_deterministic():
    start = date(2025, 1, 1)
    end = date(2025, 1, 2)
    pair = PairSpec(stock_secid="AAA", future_secid="AAA_F", expiry=date(2025, 2, 1), multiplier=1.0)

    stock_bars = {
        start: [_bar("AAA", start, 100.0)],
        start + timedelta(days=1): [_bar("AAA", start + timedelta(days=1), 110.0)],
    }
    fut_bars = {
        start: [_bar("AAA_F", start, 100.0)],
        start + timedelta(days=1): [_bar("AAA_F", start + timedelta(days=1), 100.0)],
    }
    store = InMemoryDataStore(
        stock_bars=stock_bars,
        fut_bars=fut_bars,
        key_rates=[KeyRate(date=start, rate=0.0)],
    )
    request = _make_request(start, end)
    rebalance = _rebalance_config(0.0)

    report1 = run_backtest_v2(
        request=request,
        universe=[pair],
        data_store=store,
        rebalance_config=rebalance,
        fill_time="EOD",
        initial_equity=1000.0,
    )
    report2 = run_backtest_v2(
        request=request,
        universe=[pair],
        data_store=store,
        rebalance_config=rebalance,
        fill_time="EOD",
        initial_equity=1000.0,
    )

    assert report1.summary_metrics == report2.summary_metrics
    assert report1.trades == report2.trades
    assert report1.equity_curve == report2.equity_curve


def test_backtest_v2_metrics_short_period():
    start = date(2025, 1, 1)
    end = date(2025, 1, 2)
    pair = PairSpec(stock_secid="AAA", future_secid="AAA_F", expiry=date(2025, 2, 1), multiplier=1.0)

    stock_bars = {
        start: [_bar("AAA", start, 100.0)],
        start + timedelta(days=1): [_bar("AAA", start + timedelta(days=1), 110.0)],
    }
    fut_bars = {
        start: [_bar("AAA_F", start, 100.0)],
        start + timedelta(days=1): [_bar("AAA_F", start + timedelta(days=1), 100.0)],
    }
    store = InMemoryDataStore(
        stock_bars=stock_bars,
        fut_bars=fut_bars,
        key_rates=[KeyRate(date=start, rate=0.0)],
    )
    request = _make_request(start, end)
    report = run_backtest_v2(
        request=request,
        universe=[pair],
        data_store=store,
        rebalance_config=_rebalance_config(0.0),
        fill_time="EOD",
        initial_equity=1000.0,
    )

    metrics = report.summary_metrics
    assert metrics["AvgHoldDays"] == pytest.approx(1.0)
    assert metrics["WinRate"] == pytest.approx(1.0)
    assert metrics["r_d"] == pytest.approx(0.01)
    assert metrics["MaxDD"] == pytest.approx(0.0)
    expected_cagr = (1.01 ** (365.0 / 1.0)) - 1.0
    assert metrics["CAGR"] == pytest.approx(expected_cagr)
