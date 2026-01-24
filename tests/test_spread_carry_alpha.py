from datetime import date

from moex_carry.strategy.spread_carry_alpha import SpreadCarryState, step_spread_carry_alpha


def test_spread_carry_alpha_entry_and_exit():
    state = SpreadCarryState()
    decision = step_spread_carry_alpha(
        state,
        as_of=date(2025, 1, 1),
        floor_pass=True,
        liquidity_pass=True,
        spread_pct_entry_exec=0.0,
        spread_pct_exit_exec=0.0,
        tp_net=0.01,
        sl_net=0.01,
        dte=30,
        min_dte_entry=5,
        close_buffer_days=3,
        h_max_days=20,
    )
    assert decision.action == "enter"
    assert state.position is not None

    decision = step_spread_carry_alpha(
        state,
        as_of=date(2025, 1, 2),
        floor_pass=True,
        liquidity_pass=True,
        spread_pct_entry_exec=0.0,
        spread_pct_exit_exec=0.02,
        tp_net=0.01,
        sl_net=0.01,
        dte=29,
        min_dte_entry=5,
        close_buffer_days=3,
        h_max_days=20,
    )
    assert decision.action == "exit"
    assert "tp" in decision.reasons
    assert state.position is None
