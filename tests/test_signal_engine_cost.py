from __future__ import annotations

from moex_carry.signal_engine.core.types import OutcomeForecast
from moex_carry.signal_engine.cost.model_ticks import expected_return_ticks


def test_expected_return_ticks_formula():
    forecast = OutcomeForecast(
        p_tp=0.5,
        p_sl=0.3,
        p_exit=0.2,
        n_effective=200.0,
        confidence_tier="mid",
        probability_source="unit",
    )
    expectancy = expected_return_ticks(
        forecast=forecast,
        tp_ticks=10,
        sl_ticks=5,
        cost_ticks=1.0,
        exit_return_ticks=0.0,
    )
    assert expectancy == 2.5
