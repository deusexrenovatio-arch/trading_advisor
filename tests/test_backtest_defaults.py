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
    assert strategy.sequential_entry_enabled is False
    assert strategy.sequential_entry_first_leg == "future"
    assert strategy.sequential_entry_second_leg_max_wait_minutes == 5
    assert strategy.sequential_entry_unwind_penalty_bps == 0.0
    assert strategy.sequential_exit_enabled is False
    assert strategy.sequential_exit_first_leg == "future"
    assert strategy.sequential_exit_second_leg_max_wait_minutes == 5
    assert strategy.sequential_exit_force_penalty_bps is None
