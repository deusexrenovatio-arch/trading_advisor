from __future__ import annotations

from datetime import datetime, timedelta

from moex_carry.signal_engine.core.types import HistoricalOutcome
from moex_carry.signal_engine.prob.empirical_dirichlet import (
    DirichletDecayConfig,
    estimate_outcome_probabilities,
)


def test_probability_prior_on_empty_history():
    as_of = datetime(2026, 1, 10, 12, 0, 0)
    forecast = estimate_outcome_probabilities(outcomes=[], as_of_ts=as_of)
    assert forecast.p_tp == 1.0 / 3.0
    assert forecast.p_sl == 1.0 / 3.0
    assert forecast.p_exit == 1.0 / 3.0


def test_probability_sum_is_one():
    as_of = datetime(2026, 1, 10, 12, 0, 0)
    outcomes = [
        HistoricalOutcome(ts=as_of - timedelta(days=1), outcome="TP"),
        HistoricalOutcome(ts=as_of - timedelta(days=2), outcome="SL"),
        HistoricalOutcome(ts=as_of - timedelta(days=3), outcome="EXIT"),
    ]
    forecast = estimate_outcome_probabilities(outcomes=outcomes, as_of_ts=as_of)
    assert abs((forecast.p_tp + forecast.p_sl + forecast.p_exit) - 1.0) < 1e-9


def test_n_effective_for_equal_weights_matches_count():
    as_of = datetime(2026, 1, 10, 12, 0, 0)
    outcomes = [
        HistoricalOutcome(ts=as_of, outcome="TP"),
        HistoricalOutcome(ts=as_of, outcome="SL"),
        HistoricalOutcome(ts=as_of, outcome="EXIT"),
    ]
    forecast = estimate_outcome_probabilities(
        outcomes=outcomes,
        as_of_ts=as_of,
        config=DirichletDecayConfig(half_life_days=30.0),
    )
    assert forecast.n_effective == 3.0


def test_n_effective_for_uneven_weights_is_less_than_count():
    as_of = datetime(2026, 1, 10, 12, 0, 0)
    outcomes = [
        HistoricalOutcome(ts=as_of, outcome="TP"),
        HistoricalOutcome(ts=as_of - timedelta(days=30), outcome="SL"),
        HistoricalOutcome(ts=as_of - timedelta(days=120), outcome="EXIT"),
    ]
    forecast = estimate_outcome_probabilities(
        outcomes=outcomes,
        as_of_ts=as_of,
        config=DirichletDecayConfig(half_life_days=30.0),
    )
    assert forecast.n_effective < 3.0
