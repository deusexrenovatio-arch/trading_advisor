from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.hpo.objective import compute_objective, invalid_objective
from moex_carry.hpo.runner import _evaluate_fold, _evaluate_trial, run_hpo
from moex_carry.hpo.types import FoldResult, ObjectiveConfig, WalkForwardFold


def test_portfolio_utility_with_penalties():
    metrics = {
        "PortfolioExcessAnn": 0.30,
        "PortfolioMaxDD": -0.25,
        "PortfolioIdleRatio": 0.20,
        "PortfolioForcedExitRate": 0.10,
        "PortfolioUnfilledEntryRate": 0.20,
        "PortfolioTurnover": 0.30,
    }
    cfg = ObjectiveConfig(
        mode="max",
        scope="PORTFOLIO",
        portfolio_metric="utility",
        lambda_dd=2.0,
        dd_soft_limit=0.20,
        lambda_idle=0.6,
        lambda_forced=0.4,
        lambda_unfilled=0.3,
        lambda_turnover=0.1,
        hard_max_dd=0.40,
        hard_max_idle_ratio=0.80,
        hard_max_forced_exit_rate=0.60,
        hard_max_unfilled_entry_rate=0.70,
    )
    score = compute_objective(metrics, cfg)
    expected = 0.30 - 2.0 * 0.05 - 0.6 * 0.20 - 0.4 * 0.10 - 0.3 * 0.20 - 0.1 * 0.30
    assert score == pytest.approx(expected, abs=1e-12)


def test_portfolio_hard_gate_invalidates_objective():
    metrics = {
        "PortfolioExcessAnn": 0.25,
        "PortfolioMaxDD": -0.35,
        "PortfolioIdleRatio": 0.10,
        "PortfolioForcedExitRate": 0.10,
        "PortfolioUnfilledEntryRate": 0.10,
        "PortfolioTurnover": 0.10,
    }
    cfg = ObjectiveConfig(
        mode="max",
        scope="PORTFOLIO",
        portfolio_metric="utility",
        hard_max_dd=0.30,
    )
    assert compute_objective(metrics, cfg) == invalid_objective("max")


def test_evaluate_fold_uses_portfolio_minute_path(monkeypatch):
    calls: list[tuple[date, date, date, date]] = []

    def _fake_metrics(*, request, data_dir, start_date, end_date, metric_start, metric_end):
        del request, data_dir
        calls.append((start_date, end_date, metric_start, metric_end))
        return {
            "PortfolioExcessAnn": 0.12,
            "PortfolioCAGR": 0.10,
            "PortfolioMaxDD": -0.05,
            "PortfolioIdleRatio": 0.20,
            "PortfolioForcedExitRate": 0.10,
            "PortfolioUnfilledEntryRate": 0.15,
            "PortfolioTurnover": 0.25,
        }

    monkeypatch.setattr("moex_carry.hpo.runner.compute_minute_portfolio_window_metrics", _fake_metrics)
    fold = WalkForwardFold(
        train_start=date(2025, 1, 1),
        train_end=date(2025, 1, 15),
        val_start=date(2025, 1, 16),
        val_end=date(2025, 1, 20),
        test_start=date(2025, 1, 21),
        test_end=date(2025, 1, 25),
    )
    result = _evaluate_fold(
        request=BacktestRequest(),
        fold=fold,
        data_dir=Path("."),
        objective=ObjectiveConfig(scope="PORTFOLIO"),
        evaluation_mode="CONTINUOUS",
        precompute=True,
        backtest_runner=lambda *_args, **_kwargs: None,
    )
    assert result.val_metrics["PortfolioExcessAnn"] == 0.12
    assert len(calls) == 2
    assert calls[0] == (fold.train_start, fold.test_end, fold.val_start, fold.val_end)
    assert calls[1] == (fold.train_start, fold.test_end, fold.test_start, fold.test_end)


def test_run_hpo_portfolio_trials_emit_portfolio_metrics_and_rebalance_effect(monkeypatch):
    def _fake_metrics(*, request, data_dir, start_date, end_date, metric_start, metric_end):
        del data_dir, start_date, end_date, metric_start, metric_end
        util = float(request.rebalance.target_utilization or 1.0)
        lag = float(request.strategy.execution_lag_minutes or 20.0)
        excess = 0.15 + util * 0.10 - max(lag - 20.0, 0.0) * 0.002
        idle = max(0.0, 1.0 - util)
        return {
            "PortfolioExcessAnn": excess,
            "PortfolioCAGR": excess * 0.85,
            "PortfolioMaxDD": -0.10,
            "PortfolioIdleRatio": idle,
            "PortfolioUtilizationMean": util,
            "PortfolioForcedExitRate": 0.08,
            "PortfolioUnfilledEntryRate": 0.12,
            "PortfolioTurnover": 0.20 + util * 0.05,
        }

    monkeypatch.setattr("moex_carry.hpo.runner.compute_minute_portfolio_window_metrics", _fake_metrics)

    base_request = BacktestRequest()
    base_request.execution.mode = "INTRADAY_MINUTE"
    base_request.test.start_date = date(2025, 1, 1)
    base_request.test.end_date = date(2025, 2, 28)
    base_request.strategy.execution_lag_minutes = 20
    base_request.rebalance.target_utilization = 1.0

    folds = [
        WalkForwardFold(
            train_start=date(2025, 1, 1),
            train_end=date(2025, 1, 20),
            val_start=date(2025, 1, 21),
            val_end=date(2025, 1, 25),
            test_start=date(2025, 1, 26),
            test_end=date(2025, 1, 31),
        )
    ]
    search_space = {
        "rebalance.target_utilization": {"type": "float", "min": 0.4, "max": 1.0, "step": 0.2},
        "strategy.execution_lag_minutes": {"type": "int", "min": 20, "max": 30, "step": 5},
    }
    result = run_hpo(
        base_request=base_request,
        search_space=search_space,
        folds=folds,
        data_dir=Path("."),
        objective=ObjectiveConfig(scope="PORTFOLIO"),
        max_trials=6,
        random_seed=7,
    )

    assert len(result.trials) == 6
    utilization_values = set()
    for trial in result.trials:
        assert trial.evaluation_scope == "PORTFOLIO"
        assert trial.objective_breakdown is not None
        assert "base_excess_ann" in trial.objective_breakdown
        assert len(trial.fold_results) == 1
        val_metrics = trial.fold_results[0].val_metrics
        assert "PortfolioExcessAnn" in val_metrics
        assert "PortfolioUtilizationMean" in val_metrics
        utilization_values.add(float(val_metrics["PortfolioUtilizationMean"]))

    assert len(utilization_values) > 1


def test_negative_fold_penalty_prefers_stable_trial(monkeypatch):
    fold_a = WalkForwardFold(
        train_start=date(2025, 1, 1),
        train_end=date(2025, 1, 20),
        val_start=date(2025, 1, 21),
        val_end=date(2025, 1, 25),
        test_start=date(2025, 1, 26),
        test_end=date(2025, 1, 31),
    )
    fold_b = WalkForwardFold(
        train_start=date(2025, 1, 8),
        train_end=date(2025, 1, 27),
        val_start=date(2025, 1, 28),
        val_end=date(2025, 2, 1),
        test_start=date(2025, 2, 2),
        test_end=date(2025, 2, 7),
    )
    fold_c = WalkForwardFold(
        train_start=date(2025, 1, 15),
        train_end=date(2025, 2, 3),
        val_start=date(2025, 2, 4),
        val_end=date(2025, 2, 8),
        test_start=date(2025, 2, 9),
        test_end=date(2025, 2, 14),
    )
    folds = [fold_a, fold_b, fold_c]

    unstable_by_fold = {
        fold_a.val_start: 0.26,
        fold_b.val_start: -0.08,
        fold_c.val_start: 0.27,
    }
    stable_by_fold = {
        fold_a.val_start: 0.12,
        fold_b.val_start: 0.11,
        fold_c.val_start: 0.10,
    }

    def _fake_metrics(*, request, data_dir, start_date, end_date, metric_start, metric_end):
        del data_dir, start_date, end_date, metric_end
        is_unstable = float(request.strategy.TP_pct or 0.0) >= 0.02
        source = unstable_by_fold if is_unstable else stable_by_fold
        excess = float(source.get(metric_start, 0.05))
        return {
            "PortfolioExcessAnn": excess,
            "PortfolioCAGR": excess * 0.8,
            "PortfolioMaxDD": -0.05,
            "PortfolioIdleRatio": 0.20,
            "PortfolioForcedExitRate": 0.05,
            "PortfolioUnfilledEntryRate": 0.05,
            "PortfolioTurnover": 0.20,
        }

    monkeypatch.setattr("moex_carry.hpo.runner.compute_minute_portfolio_window_metrics", _fake_metrics)

    base_request = BacktestRequest()
    objective_base = ObjectiveConfig(scope="PORTFOLIO", mode="max", lambda_negative_folds=0.0)
    objective_stable = ObjectiveConfig(scope="PORTFOLIO", mode="max", lambda_negative_folds=0.60)

    trial_unstable_base = _evaluate_trial(
        base_request=base_request,
        params={"strategy.TP_pct": 0.02},
        folds=folds,
        data_dir=Path("."),
        objective=objective_base,
        aggregation="median",
        evaluation_mode="CONTINUOUS",
        precompute=True,
        backtest_runner=lambda *_args, **_kwargs: None,
    )
    trial_stable_base = _evaluate_trial(
        base_request=base_request,
        params={"strategy.TP_pct": 0.01},
        folds=folds,
        data_dir=Path("."),
        objective=objective_base,
        aggregation="median",
        evaluation_mode="CONTINUOUS",
        precompute=True,
        backtest_runner=lambda *_args, **_kwargs: None,
    )
    assert trial_unstable_base.objective > trial_stable_base.objective

    trial_unstable_penalized = _evaluate_trial(
        base_request=base_request,
        params={"strategy.TP_pct": 0.02},
        folds=folds,
        data_dir=Path("."),
        objective=objective_stable,
        aggregation="median",
        evaluation_mode="CONTINUOUS",
        precompute=True,
        backtest_runner=lambda *_args, **_kwargs: None,
    )
    trial_stable_penalized = _evaluate_trial(
        base_request=base_request,
        params={"strategy.TP_pct": 0.01},
        folds=folds,
        data_dir=Path("."),
        objective=objective_stable,
        aggregation="median",
        evaluation_mode="CONTINUOUS",
        precompute=True,
        backtest_runner=lambda *_args, **_kwargs: None,
    )
    assert trial_unstable_penalized.objective < trial_stable_penalized.objective
    assert trial_unstable_penalized.objective_breakdown is not None
    assert trial_unstable_penalized.objective_breakdown["negative_fold_share"] == pytest.approx(1.0 / 3.0)
    assert trial_unstable_penalized.objective_breakdown["negative_fold_penalty"] > 0.0


def test_hard_max_negative_fold_share_invalidates_trial(monkeypatch):
    fold_a = WalkForwardFold(
        train_start=date(2025, 1, 1),
        train_end=date(2025, 1, 20),
        val_start=date(2025, 1, 21),
        val_end=date(2025, 1, 25),
        test_start=date(2025, 1, 26),
        test_end=date(2025, 1, 31),
    )
    fold_b = WalkForwardFold(
        train_start=date(2025, 1, 8),
        train_end=date(2025, 1, 27),
        val_start=date(2025, 1, 28),
        val_end=date(2025, 2, 1),
        test_start=date(2025, 2, 2),
        test_end=date(2025, 2, 7),
    )
    fold_c = WalkForwardFold(
        train_start=date(2025, 1, 15),
        train_end=date(2025, 2, 3),
        val_start=date(2025, 2, 4),
        val_end=date(2025, 2, 8),
        test_start=date(2025, 2, 9),
        test_end=date(2025, 2, 14),
    )

    by_fold = {
        fold_a.val_start: 0.15,
        fold_b.val_start: -0.04,
        fold_c.val_start: 0.12,
    }

    def _fake_metrics(*, request, data_dir, start_date, end_date, metric_start, metric_end):
        del request, data_dir, start_date, end_date, metric_end
        excess = float(by_fold.get(metric_start, 0.0))
        return {
            "PortfolioExcessAnn": excess,
            "PortfolioCAGR": excess * 0.8,
            "PortfolioMaxDD": -0.05,
            "PortfolioIdleRatio": 0.20,
            "PortfolioForcedExitRate": 0.05,
            "PortfolioUnfilledEntryRate": 0.05,
            "PortfolioTurnover": 0.20,
        }

    monkeypatch.setattr("moex_carry.hpo.runner.compute_minute_portfolio_window_metrics", _fake_metrics)

    trial = _evaluate_trial(
        base_request=BacktestRequest(),
        params={},
        folds=[fold_a, fold_b, fold_c],
        data_dir=Path("."),
        objective=ObjectiveConfig(scope="PORTFOLIO", mode="max", hard_max_negative_fold_share=0.2),
        aggregation="median",
        evaluation_mode="CONTINUOUS",
        precompute=True,
        backtest_runner=lambda *_args, **_kwargs: None,
    )
    assert trial.objective == invalid_objective("max")
    assert trial.objective_breakdown is not None
    assert trial.objective_breakdown["hard_negative_gate_pass"] == 0.0

def test_run_hpo_trial_cache_reuses_duplicate_params(monkeypatch):
    folds = [
        WalkForwardFold(
            train_start=date(2025, 1, 1),
            train_end=date(2025, 1, 10),
            val_start=date(2025, 1, 11),
            val_end=date(2025, 1, 12),
            test_start=date(2025, 1, 13),
            test_end=date(2025, 1, 14),
        ),
        WalkForwardFold(
            train_start=date(2025, 1, 2),
            train_end=date(2025, 1, 11),
            val_start=date(2025, 1, 12),
            val_end=date(2025, 1, 13),
            test_start=date(2025, 1, 14),
            test_end=date(2025, 1, 15),
        ),
        WalkForwardFold(
            train_start=date(2025, 1, 3),
            train_end=date(2025, 1, 12),
            val_start=date(2025, 1, 13),
            val_end=date(2025, 1, 14),
            test_start=date(2025, 1, 15),
            test_end=date(2025, 1, 16),
        ),
    ]
    sampled = [
        {"strategy.execution_lag_minutes": 20},
        {"strategy.execution_lag_minutes": 20},
        {"strategy.execution_lag_minutes": 25},
        {"strategy.execution_lag_minutes": 25},
        {"strategy.execution_lag_minutes": 20},
    ]
    sample_state = {"idx": 0}

    def _fake_sample_random(space, rng):
        del space, rng
        idx = sample_state["idx"]
        sample_state["idx"] = idx + 1
        return dict(sampled[idx])

    calls = {"count": 0}

    def _fake_evaluate_fold(*, request, fold, data_dir, objective, evaluation_mode, precompute, backtest_runner):
        del data_dir, objective, evaluation_mode, precompute, backtest_runner
        calls["count"] += 1
        val = float(request.strategy.execution_lag_minutes or 0.0) / 100.0
        return FoldResult(
            fold=fold,
            val_metrics={"ExcessAnn": val},
            test_metrics=None,
            val_objective=val,
        )

    monkeypatch.setattr("moex_carry.hpo.runner.sample_random", _fake_sample_random)
    monkeypatch.setattr("moex_carry.hpo.runner._evaluate_fold", _fake_evaluate_fold)

    result = run_hpo(
        base_request=BacktestRequest(),
        search_space={"strategy.execution_lag_minutes": {"type": "int", "min": 20, "max": 30, "step": 5}},
        folds=folds,
        data_dir=Path("."),
        objective=ObjectiveConfig(scope="PAIR_MEAN", mode="max"),
        max_trials=len(sampled),
        algorithm="RANDOM",
        random_seed=11,
    )

    assert len(result.trials) == len(sampled)
    assert calls["count"] == 2 * len(folds)


def test_run_hpo_partial_eval_and_top_refit(monkeypatch):
    folds = [
        WalkForwardFold(
            train_start=date(2025, 1, 1),
            train_end=date(2025, 1, 10),
            val_start=date(2025, 1, 11),
            val_end=date(2025, 1, 12),
            test_start=date(2025, 1, 13),
            test_end=date(2025, 1, 14),
        ),
        WalkForwardFold(
            train_start=date(2025, 1, 2),
            train_end=date(2025, 1, 11),
            val_start=date(2025, 1, 12),
            val_end=date(2025, 1, 13),
            test_start=date(2025, 1, 14),
            test_end=date(2025, 1, 15),
        ),
        WalkForwardFold(
            train_start=date(2025, 1, 3),
            train_end=date(2025, 1, 12),
            val_start=date(2025, 1, 13),
            val_end=date(2025, 1, 14),
            test_start=date(2025, 1, 15),
            test_end=date(2025, 1, 16),
        ),
        WalkForwardFold(
            train_start=date(2025, 1, 4),
            train_end=date(2025, 1, 13),
            val_start=date(2025, 1, 14),
            val_end=date(2025, 1, 15),
            test_start=date(2025, 1, 16),
            test_end=date(2025, 1, 17),
        ),
        WalkForwardFold(
            train_start=date(2025, 1, 5),
            train_end=date(2025, 1, 14),
            val_start=date(2025, 1, 15),
            val_end=date(2025, 1, 16),
            test_start=date(2025, 1, 17),
            test_end=date(2025, 1, 18),
        ),
    ]
    sampled = [
        {"strategy.execution_lag_minutes": 20},
        {"strategy.execution_lag_minutes": 25},
        {"strategy.execution_lag_minutes": 30},
    ]
    sample_state = {"idx": 0}

    def _fake_sample_random(space, rng):
        del space, rng
        idx = sample_state["idx"]
        sample_state["idx"] = idx + 1
        return dict(sampled[idx])

    calls_by_lag: dict[int, int] = {}

    def _fake_evaluate_fold(*, request, fold, data_dir, objective, evaluation_mode, precompute, backtest_runner):
        del data_dir, objective, evaluation_mode, precompute, backtest_runner
        lag = int(request.strategy.execution_lag_minutes or 0)
        calls_by_lag[lag] = calls_by_lag.get(lag, 0) + 1
        val = float(lag) / 100.0
        return FoldResult(
            fold=fold,
            val_metrics={"ExcessAnn": val},
            test_metrics=None,
            val_objective=val,
        )

    monkeypatch.setattr("moex_carry.hpo.runner.sample_random", _fake_sample_random)
    monkeypatch.setattr("moex_carry.hpo.runner._evaluate_fold", _fake_evaluate_fold)

    result = run_hpo(
        base_request=BacktestRequest(),
        search_space={"strategy.execution_lag_minutes": {"type": "int", "min": 20, "max": 30, "step": 5}},
        folds=folds,
        data_dir=Path("."),
        objective=ObjectiveConfig(scope="PAIR_MEAN", mode="max"),
        max_trials=len(sampled),
        algorithm="RANDOM",
        random_seed=17,
        max_fold_evaluations_per_trial=2,
        refit_top_n_full_folds=1,
    )

    by_lag = {int(trial.params["strategy.execution_lag_minutes"]): trial for trial in result.trials}
    assert by_lag[30].objective_breakdown is not None
    assert by_lag[30].objective_breakdown["folds_evaluated"] == pytest.approx(float(len(folds)))
    assert by_lag[30].objective_breakdown["is_partial_fold_eval"] == 0.0
    assert by_lag[20].objective_breakdown is not None
    assert by_lag[20].objective_breakdown["folds_evaluated"] == pytest.approx(2.0)
    assert by_lag[20].objective_breakdown["is_partial_fold_eval"] == 1.0

    assert calls_by_lag[20] == 2
    assert calls_by_lag[25] == 2
    assert calls_by_lag[30] == 2 + len(folds)
