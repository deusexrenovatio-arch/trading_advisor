from datetime import date

import pytest

from moex_carry.strategy.spread_carry_alpha import SpreadCarryState, step_spread_carry_alpha


def _enter_position(state: SpreadCarryState, *, direction: str = "cash_and_carry") -> None:
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
        direction=direction,
    )
    assert decision.action == "enter"
    assert state.position == direction


def test_spread_carry_alpha_cash_and_carry_favorable_move_hits_tp():
    state = SpreadCarryState()
    _enter_position(state)

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
    assert decision.metrics["pnl_spread_pct"] == pytest.approx(0.02)
    assert state.position is None


def test_spread_carry_alpha_cash_and_carry_adverse_move_hits_sl():
    state = SpreadCarryState()
    _enter_position(state)

    decision = step_spread_carry_alpha(
        state,
        as_of=date(2025, 1, 2),
        floor_pass=True,
        liquidity_pass=True,
        spread_pct_entry_exec=0.0,
        spread_pct_exit_exec=-0.02,
        tp_net=0.01,
        sl_net=0.01,
        dte=29,
        min_dte_entry=5,
        close_buffer_days=3,
        h_max_days=20,
    )
    assert decision.action == "exit"
    assert "sl" in decision.reasons
    assert decision.metrics["pnl_spread_pct"] == pytest.approx(-0.02)
    assert state.position is None


def test_spread_carry_alpha_reverse_uses_opposite_sign():
    state = SpreadCarryState()
    _enter_position(state, direction="reverse")

    decision = step_spread_carry_alpha(
        state,
        as_of=date(2025, 1, 2),
        floor_pass=True,
        liquidity_pass=True,
        spread_pct_entry_exec=0.0,
        spread_pct_exit_exec=-0.02,
        tp_net=0.01,
        sl_net=0.01,
        dte=29,
        min_dte_entry=5,
        close_buffer_days=3,
        h_max_days=20,
    )
    assert decision.action == "exit"
    assert "tp" in decision.reasons
    assert decision.metrics["pnl_spread_pct"] == pytest.approx(0.02)
    assert state.position is None
