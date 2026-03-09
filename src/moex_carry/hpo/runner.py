from __future__ import annotations

import math
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping

from moex_carry.backtest_v2.runtime import run_backtest_v2_cached
from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.hpo.minute_portfolio_pnl import compute_minute_portfolio_window_metrics
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
    parallel_fold_workers: int = 1,
    max_fold_evaluations_per_trial: int = 0,
    refit_top_n_full_folds: int = 0,
    backtest_runner: BacktestRunner | None = None,
) -> HpoResult:
    rng = random.Random(random_seed)
    space = parse_search_space(search_space)
    if backtest_runner is None:
        backtest_runner = _default_backtest_runner
    trials: list[TrialResult] = []
    trial_cache: dict[str, TrialResult] = {}
    for _ in range(max_trials):
        if algorithm == "TPE":
            params = sample_tpe(space, trials, rng, mode=objective.mode)
        else:
            params = sample_random(space, rng)
        params_sig = _params_signature(params)
        cached_trial = trial_cache.get(params_sig)
        if cached_trial is not None:
            trials.append(cached_trial)
            continue
        trial = _evaluate_trial(
            base_request=base_request,
            params=params,
            folds=folds,
            data_dir=data_dir,
            objective=objective,
            aggregation=aggregation,
            evaluation_mode=evaluation_mode,
            max_fold_evaluations=max_fold_evaluations_per_trial,
            parallel_fold_workers=parallel_fold_workers,
            precompute=precompute,
            backtest_runner=backtest_runner,
        )
        trial_cache[params_sig] = trial
        trials.append(trial)

    refit_top_n = max(int(refit_top_n_full_folds), 0)
    if refit_top_n > 0 and int(max_fold_evaluations_per_trial) > 0 and trials:
        mode = str(objective.mode).lower()
        reverse = mode != "min"
        ranked_sigs = sorted(
            trial_cache.items(),
            key=lambda item: float(item[1].objective),
            reverse=reverse,
        )
        top_sigs = [sig for sig, _trial in ranked_sigs[:refit_top_n]]
        for sig in top_sigs:
            params = trial_cache[sig].params
            full_trial = _evaluate_trial(
                base_request=base_request,
                params=params,
                folds=folds,
                data_dir=data_dir,
                objective=objective,
                aggregation=aggregation,
                evaluation_mode=evaluation_mode,
                max_fold_evaluations=0,
                parallel_fold_workers=parallel_fold_workers,
                precompute=precompute,
                backtest_runner=backtest_runner,
            )
            trial_cache[sig] = full_trial
        trials = [trial_cache.get(_params_signature(trial.params), trial) for trial in trials]

    return HpoResult(trials=trials, mode=str(objective.mode).lower())

def _default_backtest_runner(request: BacktestRequest, data_dir: Path, precompute: bool | None) -> Any:
    return run_backtest_v2_cached(
        request,
        data_dir,
        precompute=precompute,
        compute_fill_quality=False,
    )


def _evaluate_trial(
    *,
    base_request: BacktestRequest,
    params: Mapping[str, Any],
    folds: list[WalkForwardFold],
    data_dir: Path,
    objective: ObjectiveConfig,
    aggregation: AggregationMode = "median",
    evaluation_mode: EvaluationMode = "CONTINUOUS",
    max_fold_evaluations: int = 0,
    parallel_fold_workers: int = 1,
    precompute: bool | None = None,
    backtest_runner: BacktestRunner = _default_backtest_runner,
) -> TrialResult:
    request = _apply_params(base_request, params)
    evaluation_scope = _objective_scope(objective)
    eval_folds = _select_fold_subset(folds, max_fold_evaluations)
    worker_count = max(int(parallel_fold_workers), 1)

    fold_results: list[FoldResult] = []
    fold_objectives: list[float] = []
    if worker_count <= 1 or len(eval_folds) <= 1:
        for fold in eval_folds:
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
    else:
        ordered: list[FoldResult | None] = [None] * len(eval_folds)
        with ThreadPoolExecutor(max_workers=min(worker_count, len(eval_folds))) as pool:
            future_to_idx = {
                pool.submit(
                    _evaluate_fold,
                    request=request,
                    fold=fold,
                    data_dir=data_dir,
                    objective=objective,
                    evaluation_mode=evaluation_mode,
                    precompute=precompute,
                    backtest_runner=backtest_runner,
                ): idx
                for idx, fold in enumerate(eval_folds)
            }
            for future in as_completed(future_to_idx):
                ordered[future_to_idx[future]] = future.result()
        fold_results = [item for item in ordered if item is not None]
        fold_objectives = [item.val_objective for item in fold_results]

    aggregated = aggregate_objectives(fold_objectives, aggregation, objective_mode=objective.mode)
    negative_stats = _negative_fold_stats(fold_results=fold_results, objective=objective)
    negative_penalty = float(objective.lambda_negative_folds) * float(negative_stats["negative_share"])
    hard_negative_gate_pass = True
    hard_negative_share = _as_float_or_none(objective.hard_max_negative_fold_share)
    if hard_negative_share is not None and float(negative_stats["negative_share"]) > hard_negative_share:
        aggregated = invalid_objective(objective.mode)
        hard_negative_gate_pass = False
    else:
        if str(objective.mode).lower() == "min":
            aggregated += negative_penalty
        else:
            aggregated -= negative_penalty
    objective_breakdown = _build_objective_breakdown(
        fold_results=fold_results,
        objective=objective,
    )
    if objective_breakdown is None:
        objective_breakdown = {}
    objective_breakdown.update(
        {
            "negative_fold_count": float(negative_stats["negative_fold_count"]),
            "positive_fold_count": float(negative_stats["positive_fold_count"]),
            "negative_fold_share": float(negative_stats["negative_share"]),
            "negative_fold_threshold": float(objective.negative_fold_threshold),
            "negative_fold_penalty": float(negative_penalty),
            "hard_negative_gate_pass": 1.0 if hard_negative_gate_pass else 0.0,
            "folds_total": float(len(folds)),
            "folds_evaluated": float(len(fold_results)),
            "is_partial_fold_eval": 1.0 if len(fold_results) < len(folds) else 0.0,
        }
    )
    return TrialResult(
        params=dict(params),
        objective=aggregated,
        fold_objectives=fold_objectives,
        fold_results=fold_results,
        evaluation_scope=evaluation_scope,
        objective_breakdown=objective_breakdown,
    )

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
        if _is_portfolio_scope(objective):
            val_metrics, test_metrics = _evaluate_portfolio_minute(
                request=request,
                fold=fold,
                data_dir=data_dir,
            )
        else:
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


def _evaluate_portfolio_minute(
    *,
    request: BacktestRequest,
    fold: WalkForwardFold,
    data_dir: Path,
) -> tuple[dict[str, float], dict[str, float]]:
    val_metrics = compute_minute_portfolio_window_metrics(
        request=request,
        data_dir=data_dir,
        start_date=fold.train_start,
        end_date=fold.test_end,
        metric_start=fold.val_start,
        metric_end=fold.val_end,
    )
    test_metrics = compute_minute_portfolio_window_metrics(
        request=request,
        data_dir=data_dir,
        start_date=fold.train_start,
        end_date=fold.test_end,
        metric_start=fold.test_start,
        metric_end=fold.test_end,
    )
    return val_metrics, test_metrics


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



def _params_signature(params: Mapping[str, Any]) -> str:
    normalized = {str(key): params[key] for key in sorted(params.keys())}
    return str(normalized)


def _select_fold_subset(folds: list[WalkForwardFold], max_fold_evaluations: int) -> list[WalkForwardFold]:
    if not folds:
        return []
    limit = max(int(max_fold_evaluations), 0)
    if limit <= 0 or limit >= len(folds):
        return list(folds)
    if limit == 1:
        return [folds[-1]]
    if limit == 2:
        return [folds[0], folds[-1]]

    last_idx = len(folds) - 1
    selected = {0, last_idx}
    middle_slots = limit - 2
    if middle_slots > 0 and last_idx > 1:
        for slot in range(1, middle_slots + 1):
            ratio = slot / float(middle_slots + 1)
            idx = int(round(ratio * last_idx))
            idx = min(max(idx, 1), max(last_idx - 1, 1))
            selected.add(idx)
    ordered_idx = sorted(selected)
    if len(ordered_idx) > limit:
        ordered_idx = ordered_idx[:limit]
    while len(ordered_idx) < limit:
        for idx in range(last_idx + 1):
            if idx not in selected:
                ordered_idx.append(idx)
                selected.add(idx)
                if len(ordered_idx) >= limit:
                    break
    ordered_idx = sorted(ordered_idx[:limit])
    return [folds[idx] for idx in ordered_idx]

def _objective_scope(objective: ObjectiveConfig) -> str:
    return str(objective.scope or "PORTFOLIO").upper()


def _is_portfolio_scope(objective: ObjectiveConfig) -> bool:
    return _objective_scope(objective) == "PORTFOLIO"


def _build_objective_breakdown(
    *,
    fold_results: list[FoldResult],
    objective: ObjectiveConfig,
) -> dict[str, float] | None:
    val_metrics = [result.val_metrics for result in fold_results if isinstance(result.val_metrics, dict)]
    if not val_metrics:
        return None

    scope = _objective_scope(objective)
    if scope != "PORTFOLIO":
        metric_values = [_metric_value(metrics, objective.metric) for metrics in val_metrics]
        metric_mean = _finite_mean(metric_values)
        if metric_mean is None:
            return None
        return {
            "metric_mean": float(metric_mean),
        }

    base_excess_ann = _finite_mean(
        [
            _first_finite(metrics.get("PortfolioExcessAnn"), metrics.get("ExcessAnn"))
            for metrics in val_metrics
        ]
    )
    if base_excess_ann is None:
        return None
    base_cagr = _finite_mean(
        [
            _first_finite(metrics.get("PortfolioCAGR"), metrics.get("CAGR"))
            for metrics in val_metrics
        ]
    )
    max_dd = _finite_mean(
        [abs(float(value)) for value in (_first_finite(metrics.get("PortfolioMaxDD"), metrics.get("MaxDD")) for metrics in val_metrics) if value is not None]
    ) or 0.0
    idle_ratio = _finite_mean([_first_finite(metrics.get("PortfolioIdleRatio")) for metrics in val_metrics]) or 0.0
    forced_exit_rate = _finite_mean(
        [_first_finite(metrics.get("PortfolioForcedExitRate")) for metrics in val_metrics]
    ) or 0.0
    unfilled_entry_rate = _finite_mean(
        [_first_finite(metrics.get("PortfolioUnfilledEntryRate")) for metrics in val_metrics]
    ) or 0.0
    turnover = _finite_mean(
        [
            _first_finite(metrics.get("PortfolioTurnover"), metrics.get("AvgTurnover"))
            for metrics in val_metrics
        ]
    ) or 0.0

    dd_soft_limit = abs(float(objective.dd_soft_limit))
    penalty_dd = float(objective.lambda_dd) * max(0.0, float(max_dd) - dd_soft_limit)
    penalty_idle = float(objective.lambda_idle) * float(idle_ratio)
    penalty_forced = float(objective.lambda_forced) * float(forced_exit_rate)
    penalty_unfilled = float(objective.lambda_unfilled) * float(unfilled_entry_rate)
    penalty_turnover = float(objective.lambda_turnover) * float(turnover)
    total_penalty = penalty_dd + penalty_idle + penalty_forced + penalty_unfilled + penalty_turnover

    portfolio_metric = str(objective.portfolio_metric or "utility").lower()
    base_metric = float(base_cagr) if portfolio_metric == "cagr" and base_cagr is not None else float(base_excess_ann)
    utility = float(base_excess_ann) - total_penalty

    hard_max_dd = _as_float_or_none(objective.hard_max_dd)
    hard_max_idle = _as_float_or_none(objective.hard_max_idle_ratio)
    hard_max_forced = _as_float_or_none(objective.hard_max_forced_exit_rate)
    hard_max_unfilled = _as_float_or_none(objective.hard_max_unfilled_entry_rate)
    hard_gate_pass = True
    if hard_max_dd is not None and float(max_dd) > hard_max_dd:
        hard_gate_pass = False
    if hard_max_idle is not None and float(idle_ratio) > hard_max_idle:
        hard_gate_pass = False
    if hard_max_forced is not None and float(forced_exit_rate) > hard_max_forced:
        hard_gate_pass = False
    if hard_max_unfilled is not None and float(unfilled_entry_rate) > hard_max_unfilled:
        hard_gate_pass = False

    return {
        "base_excess_ann": float(base_excess_ann),
        "base_cagr": float(base_cagr or 0.0),
        "base_metric": float(base_metric),
        "portfolio_metric": 1.0 if portfolio_metric == "cagr" else 0.0,
        "max_dd": float(max_dd),
        "idle_ratio": float(idle_ratio),
        "forced_exit_rate": float(forced_exit_rate),
        "unfilled_entry_rate": float(unfilled_entry_rate),
        "turnover": float(turnover),
        "penalty_dd": float(penalty_dd),
        "penalty_idle": float(penalty_idle),
        "penalty_forced": float(penalty_forced),
        "penalty_unfilled": float(penalty_unfilled),
        "penalty_turnover": float(penalty_turnover),
        "penalty_total": float(total_penalty),
        "utility": float(utility),
        "hard_gate_pass": 1.0 if hard_gate_pass else 0.0,
    }


def _negative_fold_stats(
    *,
    fold_results: list[FoldResult],
    objective: ObjectiveConfig,
) -> dict[str, float]:
    threshold = float(objective.negative_fold_threshold)
    considered = 0
    negative = 0
    for result in fold_results:
        metrics = result.val_metrics
        if not isinstance(metrics, Mapping):
            continue
        value = _negative_fold_metric_value(metrics=metrics, objective=objective)
        if value is None:
            continue
        considered += 1
        if float(value) <= threshold:
            negative += 1
    if considered <= 0:
        return {
            "negative_fold_count": 0.0,
            "positive_fold_count": 0.0,
            "negative_share": 1.0,
        }
    return {
        "negative_fold_count": float(negative),
        "positive_fold_count": float(max(considered - negative, 0)),
        "negative_share": float(negative / considered),
    }


def _negative_fold_metric_value(
    *,
    metrics: Mapping[str, Any],
    objective: ObjectiveConfig,
) -> float | None:
    configured_metric = str(objective.negative_fold_metric or "").strip().lower()
    if configured_metric in {"utility", "portfolio_utility"}:
        return float(compute_objective(metrics, objective))
    if configured_metric:
        return _metric_value(metrics, configured_metric)
    if _is_portfolio_scope(objective):
        return _first_finite(metrics.get("PortfolioExcessAnn"), metrics.get("ExcessAnn"))
    return _metric_value(metrics, objective.metric)


def _metric_value(metrics: Mapping[str, Any], metric_name: str | None) -> float | None:
    key = str(metric_name or "excess_ann").lower()
    if key in {"excessann", "excess_ann", "excess"}:
        return _first_finite(metrics.get("ExcessAnn"))
    if key in {"portfolio_excessann", "portfolio_excess_ann", "portfolio_excess"}:
        return _first_finite(metrics.get("PortfolioExcessAnn"), metrics.get("ExcessAnn"))
    if key in {"portfolio_cagr"}:
        return _first_finite(metrics.get("PortfolioCAGR"), metrics.get("CAGR"))
    if key in {"portfolio_maxdd", "portfolio_max_dd"}:
        value = _first_finite(metrics.get("PortfolioMaxDD"), metrics.get("MaxDD"))
        return abs(float(value)) if value is not None else None
    if key in {"cagr"}:
        return _first_finite(metrics.get("CAGR"))
    if key in {"ir"}:
        return _first_finite(metrics.get("IR"))
    if key in {"maxdd", "max_dd"}:
        value = _first_finite(metrics.get("MaxDD"))
        return abs(float(value)) if value is not None else None
    return _first_finite(metrics.get("ExcessAnn"))


def _first_finite(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric):
            return numeric
    return None


def _finite_mean(values: list[float | None]) -> float | None:
    cleaned = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not cleaned:
        return None
    return float(sum(cleaned) / len(cleaned))


def _as_float_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return numeric
