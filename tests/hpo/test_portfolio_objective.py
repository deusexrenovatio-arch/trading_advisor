from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.hpo.objective import compute_objective, invalid_objective
from moex_carry.hpo.runner import _evaluate_fold, run_hpo
from moex_carry.hpo.types import ObjectiveConfig, WalkForwardFold


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
