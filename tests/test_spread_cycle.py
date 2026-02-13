import pytest

from moex_carry.strategy.spread_cycle import SpreadCycleState, update_spread_cycle


def test_cycle_return_cash_and_carry_positive_on_spread_increase():
    state = SpreadCycleState()
    update_spread_cycle(state, action="enter", direction="cash_and_carry", spread=1.0, spot=100.0)

    result = update_spread_cycle(state, action="exit", direction=None, spread=3.0, spot=100.0)

    assert result.cycle_return_pct == pytest.approx(2.0)


def test_cycle_return_cash_and_carry_negative_on_spread_decrease():
    state = SpreadCycleState()
    update_spread_cycle(state, action="enter", direction="cash_and_carry", spread=1.0, spot=100.0)

    result = update_spread_cycle(state, action="exit", direction=None, spread=-1.0, spot=100.0)

    assert result.cycle_return_pct == pytest.approx(-2.0)


def test_cycle_return_reverse_positive_on_spread_decrease():
    state = SpreadCycleState()
    update_spread_cycle(state, action="enter", direction="reverse", spread=1.0, spot=100.0)

    result = update_spread_cycle(state, action="exit", direction=None, spread=-1.0, spot=100.0)

    assert result.cycle_return_pct == pytest.approx(2.0)
