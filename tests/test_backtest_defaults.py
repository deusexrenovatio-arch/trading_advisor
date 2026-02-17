from __future__ import annotations

from moex_carry.contracts.strategy_test import BacktestRequest


def test_minute_strategy_defaults_are_canonical():
    request = BacktestRequest()
    strategy = request.strategy
    assert strategy.signal_exec_lag_days == 0
    assert strategy.execution_lag_minutes == 30
    assert strategy.execution_max_wait_minutes == 360
    assert strategy.entry_price_tolerance_pct == 0.02
    assert strategy.entry_stock_tolerance_pct == 0.02
    assert strategy.entry_future_tolerance_pct == 0.025
    assert strategy.entry_spread_tolerance_pct == 0.03
