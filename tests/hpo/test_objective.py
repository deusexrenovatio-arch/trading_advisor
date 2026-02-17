from moex_carry.hpo.objective import compute_objective, invalid_objective
from moex_carry.hpo.types import ObjectiveConfig


def test_constraints_return_neg_inf():
    metrics = {"ex_d": 0.001, "MaxDD": -0.2, "AvgTurnover": 0.3}
    config = ObjectiveConfig(scope="PAIR_MEAN", lambda_dd=1.0, dd_max=0.1, lambda_to=1.0, to_max=0.2)
    assert compute_objective(metrics, config) == invalid_objective(config.mode)


def test_objective_computation_without_violations():
    metrics = {"ex_d": 0.002, "MaxDD": -0.05, "AvgTurnover": 0.1}
    config = ObjectiveConfig(scope="PAIR_MEAN", lambda_dd=1.0, dd_max=0.1, lambda_to=1.0, to_max=0.2)
    expected = 0.002 * 252.0
    assert compute_objective(metrics, config) == expected
