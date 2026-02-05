from __future__ import annotations

import math
import random
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping

from moex_carry.backtest_v2.runtime import run_backtest_v2_cached
from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.hpo.objective import aggregate_objectives, compute_objective, compute_window_metrics, invalid_objective
from moex_carry.hpo.search_space import parse_search_space, sample_random, sample_tpe
from moex_carry.hpo.types import (
    AggregationMode,
    Algorithm,
    EvaluationMode,
    FoldResult,
    HpoResult,
    ObjectiveConfig,
    TrialResult,
    WalkForwardFold,
)

BacktestRunner = Callable[[BacktestRequest, Path, bool | None], Any]


def run_hpo(
    *,
    base_request: BacktestRequest,
    search_space: Mapping[str, Any],
    folds: list[WalkForwardFold],
    data_dir: Path,
    objective: ObjectiveConfig,
    aggregation: AggregationMode = "median",
    algorithm: Algorithm = "RANDOM",
    max_trials: int = 50,
    random_seed: int | None = None,
    evaluation_mode: EvaluationMode = "CONTINUOUS",
    precompute: bool | None = None,
    backtest_runner: BacktestRunner | None = None,
) -> HpoResult:
    rng = random.Random(random_seed)
    space = parse_search_space(search_space)
    if backtest_runner is None:
        backtest_runner = _default_backtest_runner
    trials: list[TrialResult] = []
    for _ in range(max_trials):
        if algorithm == "TPE":
            params = sample_tpe(space, trials, rng, mode=objective.mode)
        else:
            params = sample_random(space, rng)
        trial = _evaluate_trial(
            base_request=base_request,
            params=params,
            folds=folds,
            data_dir=data_dir,
            objective=objective,
            aggregation=aggregation,
            evaluation_mode=evaluation_mode,
            precompute=precompute,
            backtest_runner=backtest_runner,
        )
        trials.append(trial)
    return HpoResult(trials=trials, mode=str(objective.mode).lower())


def _default_backtest_runner(request: BacktestRequest, data_dir: Path, precompute: bool | None) -> Any:
    return run_backtest_v2_cached(request, data_dir, precompute=precompute)


def _evaluate_trial(
    *,
    base_request: BacktestRequest,
    params: Mapping[str, Any],
    folds: list[WalkForwardFold],
    data_dir: Path,
    objective: ObjectiveConfig,
    aggregation: AggregationMode,
    evaluation_mode: EvaluationMode,
    precompute: bool | None,
    backtest_runner: BacktestRunner,
) -> TrialResult:
    request = _apply_params(base_request, params)
    fold_results: list[FoldResult] = []
    fold_objectives: list[float] = []
    for fold in folds:
        result = _evaluate_fold(
            request=request,
            fold=fold,
            data_dir=data_dir,
            objective=objective,
            evaluation_mode=evaluation_mode,
            precompute=precompute,
            backtest_runner=backtest_runner,
        )
        fold_results.append(result)
        fold_objectives.append(result.val_objective)
    aggregated = aggregate_objectives(fold_objectives, aggregation, objective_mode=objective.mode)
    return TrialResult(params=dict(params), objective=aggregated, fold_objectives=fold_objectives, fold_results=fold_results)


def _evaluate_fold(
    *,
    request: BacktestRequest,
    fold: WalkForwardFold,
    data_dir: Path,
    objective: ObjectiveConfig,
    evaluation_mode: EvaluationMode,
    precompute: bool | None,
    backtest_runner: BacktestRunner,
) -> FoldResult:
    try:
        if evaluation_mode == "WARMUP_THEN_FLAT":
            val_metrics, test_metrics = _evaluate_warmup_then_flat(
                request=request,
                fold=fold,
                data_dir=data_dir,
                precompute=precompute,
                backtest_runner=backtest_runner,
            )
        else:
            val_metrics, test_metrics = _evaluate_continuous(
                request=request,
                fold=fold,
                data_dir=data_dir,
                precompute=precompute,
                backtest_runner=backtest_runner,
            )
        val_objective = compute_objective(val_metrics, objective)
    except Exception:
        val_metrics = {}
        test_metrics = None
        val_objective = invalid_objective(objective.mode)
    return FoldResult(
        fold=fold,
        val_metrics=val_metrics,
        test_metrics=test_metrics,
        val_objective=val_objective,
    )


def _evaluate_continuous(
    *,
    request: BacktestRequest,
    fold: WalkForwardFold,
    data_dir: Path,
    precompute: bool | None,
    backtest_runner: BacktestRunner,
) -> tuple[dict[str, float], dict[str, float]]:
    full_request = _update_request(request, start_date=fold.train_start, end_date=fold.test_end)
    report = backtest_runner(full_request, data_dir, precompute)
    val_metrics = compute_window_metrics(report, fold.val_start, fold.val_end, data_dir)
    test_metrics = compute_window_metrics(report, fold.test_start, fold.test_end, data_dir)
    return val_metrics, test_metrics


def _evaluate_warmup_then_flat(
    *,
    request: BacktestRequest,
    fold: WalkForwardFold,
    data_dir: Path,
    precompute: bool | None,
    backtest_runner: BacktestRunner,
) -> tuple[dict[str, float], dict[str, float]]:
    val_equity = _warmup_equity(request, fold.train_start, fold.val_start, data_dir, precompute, backtest_runner)
    val_request = _update_request(
        request,
        start_date=fold.val_start,
        end_date=fold.val_end,
        account_equity=val_equity,
    )
    val_report = backtest_runner(val_request, data_dir, precompute)
    val_metrics = val_report.summary_metrics

    test_equity = _warmup_equity(request, fold.train_start, fold.test_start, data_dir, precompute, backtest_runner)
    test_request = _update_request(
        request,
        start_date=fold.test_start,
        end_date=fold.test_end,
        account_equity=test_equity,
    )
    test_report = backtest_runner(test_request, data_dir, precompute)
    test_metrics = test_report.summary_metrics
    return val_metrics, test_metrics


def _warmup_equity(
    request: BacktestRequest,
    start_date: date,
    end_date: date,
    data_dir: Path,
    precompute: bool | None,
    backtest_runner: BacktestRunner,
) -> float:
    warm_request = _update_request(request, start_date=start_date, end_date=end_date)
    report = backtest_runner(warm_request, data_dir, precompute)
    if not report.equity_curve:
        return float(request.portfolio.account_equity or 0.0)
    return float(report.equity_curve[-1].equity)


def _apply_params(base_request: BacktestRequest, params: Mapping[str, Any]) -> BacktestRequest:
    payload = base_request.model_dump(mode="python")
    for key, value in params.items():
        _set_nested(payload, key.split("."), value)
    return BacktestRequest.model_validate(payload)


def _update_request(
    request: BacktestRequest,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    account_equity: float | None = None,
) -> BacktestRequest:
    payload = request.model_dump(mode="python")
    if start_date is not None:
        payload.setdefault("test", {})["start_date"] = start_date
    if end_date is not None:
        payload.setdefault("test", {})["end_date"] = end_date
    if account_equity is not None and math.isfinite(float(account_equity)):
        payload.setdefault("portfolio", {})["account_equity"] = float(account_equity)
    return BacktestRequest.model_validate(payload)


def _set_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    if not path:
        return
    key = path[0]
    if len(path) == 1:
        target[key] = value
        return
    if key not in target or not isinstance(target[key], dict):
        target[key] = {}
    _set_nested(target[key], path[1:], value)
