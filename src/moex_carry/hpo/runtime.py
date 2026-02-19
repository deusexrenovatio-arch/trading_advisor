from __future__ import annotations

import json
import math
import random
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from moex_carry.backtest_v2.runtime import build_universe_from_request, run_backtest_v2_cached
from moex_carry.contracts.strategy_test import HpoRequest
from moex_carry.data.history_store import HistoryDataStore
from moex_carry.hpo.folds import build_walk_forward_folds
from moex_carry.hpo.objective import ObjectiveConfig, invalid_objective
from moex_carry.hpo.runner import _apply_params, _default_backtest_runner, _evaluate_trial
from moex_carry.hpo.search_space import parse_search_space, sample_random, sample_tpe
from moex_carry.hpo.types import AggregationMode, EvaluationMode, HpoResult, TrialResult


DEFAULT_TRAIN_DAYS = 756
DEFAULT_VAL_DAYS = 126
DEFAULT_TEST_DAYS = 126
DEFAULT_STEP_DAYS = 21
DEFAULT_MAX_TRIALS = 10
DEFAULT_ALGORITHM = "RANDOM"
DEFAULT_AGGREGATION: AggregationMode = "median"
DEFAULT_EVALUATION: EvaluationMode = "CONTINUOUS"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_dir(data_dir: Path, run_id: str) -> Path:
    return Path(data_dir) / "hpo" / "runs" / run_id


def _active_run_path(data_dir: Path) -> Path:
    return Path(data_dir) / "hpo" / "active_run.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _status_path(run_dir: Path) -> Path:
    return run_dir / "status.json"


def _result_path(run_dir: Path) -> Path:
    return run_dir / "result.json"


def _write_active_run(data_dir: Path, run_id: str, created_at: str) -> None:
    _write_json(_active_run_path(data_dir), {"run_id": run_id, "created_at": created_at})


def _load_active_run(data_dir: Path) -> str | None:
    payload = _read_json(_active_run_path(data_dir))
    run_id = payload.get("run_id") if payload else None
    return str(run_id) if run_id else None


def _serialize_fold(fold) -> dict[str, Any]:
    return {
        "train_start": fold.train_start.isoformat(),
        "train_end": fold.train_end.isoformat(),
        "val_start": fold.val_start.isoformat(),
        "val_end": fold.val_end.isoformat(),
        "test_start": fold.test_start.isoformat(),
        "test_end": fold.test_end.isoformat(),
    }


def _serialize_fold_result(result) -> dict[str, Any]:
    return {
        "fold": _serialize_fold(result.fold),
        "val_metrics": result.val_metrics,
        "test_metrics": result.test_metrics,
        "val_objective": result.val_objective,
    }


def _serialize_trial(trial: TrialResult) -> dict[str, Any]:
    return {
        "params": trial.params,
        "objective": trial.objective,
        "fold_objectives": list(trial.fold_objectives),
        "fold_results": [_serialize_fold_result(item) for item in trial.fold_results],
        "evaluation_scope": trial.evaluation_scope,
        "objective_breakdown": trial.objective_breakdown,
    }


def _serialize_result(result: HpoResult) -> dict[str, Any]:
    trials = [_serialize_trial(trial) for trial in result.trials]
    leaderboard = [_serialize_trial(trial) for trial in result.leaderboard()]
    return {
        "mode": result.mode,
        "trials": trials,
        "leaderboard": leaderboard,
    }


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _compute_quality_penalty(
    *,
    unfilled_entry_rate: float | None,
    forced_exit_rate: float | None,
    entry_wait_min_closed: float | None,
    exit_wait_min_closed: float | None,
    optimization: Any,
) -> float:
    penalty = 0.0
    if unfilled_entry_rate is not None:
        penalty += float(optimization.quality_lambda_unfilled) * max(0.0, unfilled_entry_rate)
    if forced_exit_rate is not None:
        penalty += float(optimization.quality_lambda_forced) * max(0.0, forced_exit_rate)
    wait_limit = max(
        1.0,
        float(optimization.quality_max_entry_wait_min_closed),
        float(optimization.quality_max_exit_wait_min_closed),
    )
    wait_values = [
        value
        for value in (entry_wait_min_closed, exit_wait_min_closed)
        if value is not None
    ]
    if wait_values:
        wait_mean = sum(wait_values) / len(wait_values)
        penalty += float(optimization.quality_lambda_wait) * max(0.0, wait_mean / wait_limit)
    return float(penalty)


def _evaluate_trial_quality_review(
    *,
    request: HpoRequest,
    trial: TrialResult,
    rank: int,
    data_dir: Path,
    precompute: bool | None,
    mode: str,
) -> dict[str, Any]:
    candidate_request = _apply_params(request.base, trial.params)
    report = run_backtest_v2_cached(
        candidate_request,
        data_dir,
        precompute=precompute,
        compute_fill_quality=True,
    )
    summary = report.fill_quality_summary or {}
    unfilled_entry_rate = _safe_float(summary.get("unfilled_entry_rate_mean"))
    forced_exit_rate = _safe_float(summary.get("forced_exit_rate_mean"))
    entry_wait_min_closed = _safe_float(summary.get("avg_entry_wait_min_closed_mean"))
    exit_wait_min_closed = _safe_float(summary.get("avg_exit_wait_min_closed_mean"))
    trades_closed_total = int(_safe_float(summary.get("trades_closed_total")) or 0)

    gate_reasons: list[str] = []
    optimization = request.optimization
    if trades_closed_total < int(optimization.quality_min_trades_closed_total):
        gate_reasons.append("quality_gate_trades_closed_total")
    if (
        unfilled_entry_rate is not None
        and unfilled_entry_rate > float(optimization.quality_max_unfilled_entry_rate)
    ):
        gate_reasons.append("quality_gate_unfilled_entry_rate")
    if (
        forced_exit_rate is not None
        and forced_exit_rate > float(optimization.quality_max_forced_exit_rate)
    ):
        gate_reasons.append("quality_gate_forced_exit_rate")
    if (
        entry_wait_min_closed is not None
        and entry_wait_min_closed > float(optimization.quality_max_entry_wait_min_closed)
    ):
        gate_reasons.append("quality_gate_entry_wait")
    if (
        exit_wait_min_closed is not None
        and exit_wait_min_closed > float(optimization.quality_max_exit_wait_min_closed)
    ):
        gate_reasons.append("quality_gate_exit_wait")

    quality_gate_pass = len(gate_reasons) == 0
    quality_penalty = _compute_quality_penalty(
        unfilled_entry_rate=unfilled_entry_rate,
        forced_exit_rate=forced_exit_rate,
        entry_wait_min_closed=entry_wait_min_closed,
        exit_wait_min_closed=exit_wait_min_closed,
        optimization=optimization,
    )
    objective_quality = (
        float(trial.objective - quality_penalty)
        if mode == "max"
        else float(trial.objective + quality_penalty)
    )
    if not quality_gate_pass:
        objective_quality = invalid_objective(mode)

    return {
        "rank_base": int(rank),
        "params": dict(trial.params),
        "objective_base": float(trial.objective),
        "quality_gate_pass": bool(quality_gate_pass),
        "quality_gate_reasons": gate_reasons,
        "quality_penalty": float(quality_penalty),
        "objective_quality": float(objective_quality),
        "quality_metrics": {
            "unfilled_entry_rate_mean": unfilled_entry_rate,
            "forced_exit_rate_mean": forced_exit_rate,
            "avg_entry_wait_min_closed_mean": entry_wait_min_closed,
            "avg_exit_wait_min_closed_mean": exit_wait_min_closed,
            "trades_closed_total": trades_closed_total,
            "pairs_ok": int(_safe_float(summary.get("pairs_ok")) or 0),
            "pairs_total": int(_safe_float(summary.get("pairs_total")) or 0),
        },
    }


def _build_quality_review(
    *,
    request: HpoRequest,
    result: HpoResult,
    data_dir: Path,
    precompute: bool | None,
) -> dict[str, Any] | None:
    if not bool(request.optimization.quality_review_enabled):
        return None
    execution_mode = str(request.base.execution.mode or "INTRADAY_MINUTE").upper()
    if execution_mode != "INTRADAY_MINUTE":
        return {
            "enabled": True,
            "skipped": True,
            "reason": "execution_mode_not_intraday_minute",
            "execution_mode": execution_mode,
            "candidates": [],
        }

    leaderboard = result.leaderboard()
    top_n = max(int(request.optimization.quality_top_n or 0), 0)
    selected = leaderboard[:top_n] if top_n > 0 else []
    if not selected:
        return {
            "enabled": True,
            "skipped": False,
            "reason": "no_candidates",
            "top_n_requested": top_n,
            "candidates": [],
        }

    rows: list[dict[str, Any]] = []
    for rank, trial in enumerate(selected, start=1):
        rows.append(
            _evaluate_trial_quality_review(
                request=request,
                trial=trial,
                rank=rank,
                data_dir=data_dir,
                precompute=precompute,
                mode=result.mode,
            )
        )
    rows = sorted(
        rows,
        key=lambda row: float(row["objective_quality"]),
        reverse=result.mode == "max",
    )
    pass_count = sum(1 for row in rows if bool(row.get("quality_gate_pass")))
    return {
        "enabled": True,
        "skipped": False,
        "top_n_requested": top_n,
        "top_n_evaluated": len(rows),
        "quality_gate_pass_count": int(pass_count),
        "quality_gate_pass_rate": float(pass_count / len(rows)) if rows else 0.0,
        "defaults": {
            "quality_min_trades_closed_total": int(request.optimization.quality_min_trades_closed_total),
            "quality_max_unfilled_entry_rate": float(request.optimization.quality_max_unfilled_entry_rate),
            "quality_max_forced_exit_rate": float(request.optimization.quality_max_forced_exit_rate),
            "quality_max_entry_wait_min_closed": float(request.optimization.quality_max_entry_wait_min_closed),
            "quality_max_exit_wait_min_closed": float(request.optimization.quality_max_exit_wait_min_closed),
            "quality_lambda_unfilled": float(request.optimization.quality_lambda_unfilled),
            "quality_lambda_forced": float(request.optimization.quality_lambda_forced),
            "quality_lambda_wait": float(request.optimization.quality_lambda_wait),
        },
        "best_quality_candidate": rows[0] if rows else None,
        "candidates": rows,
    }


def _resolve_fold_lengths(total_days: int, request: HpoRequest) -> tuple[int, int, int, int]:
    train_days = DEFAULT_TRAIN_DAYS
    val_days = DEFAULT_VAL_DAYS
    test_days = DEFAULT_TEST_DAYS
    step_days = DEFAULT_STEP_DAYS
    test_size = request.cv.test_size
    if isinstance(test_size, (int, float)) and 0 < float(test_size) < 0.5:
        test_days = max(1, int(total_days * float(test_size)))
        val_days = test_days
        step_days = test_days
        if train_days + val_days + test_days > total_days:
            train_days = max(1, total_days - val_days - test_days)
    return train_days, val_days, test_days, step_days


def _fallback_fold_lengths(total_days: int) -> tuple[int, int, int, int]:
    test_days = max(5, int(total_days * 0.2))
    val_days = test_days
    train_days = max(5, total_days - val_days - test_days)
    step_days = max(1, test_days)
    return train_days, val_days, test_days, step_days


def _coerce_calendar_day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # ISO dates are expected in cached minute series payloads.
    if len(text) >= 10:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def _minute_calendar_dates(
    *,
    request: Any,
    data_dir: Path,
    universe: list[Any],
) -> list[date]:
    from moex_carry.signal_replay import load_pair_minute_series

    start_date = request.test.start_date
    end_date = request.test.end_date
    if start_date is None or end_date is None:
        return []
    days: set[date] = set()
    for pair in universe:
        payload = load_pair_minute_series(
            data_dir=data_dir,
            stock=pair.stock_secid,
            future=pair.future_secid,
            start_date=start_date,
            end_date=end_date,
        )
        if payload is None or payload.series_base is None or payload.series_base.empty:
            continue
        frame = payload.series_base
        if "date" in frame.columns:
            values = frame["date"].tolist()
        elif "exec_ts" in frame.columns:
            values = frame["exec_ts"].tolist()
        else:
            continue
        for raw in values:
            day = _coerce_calendar_day(raw)
            if day is None:
                continue
            if start_date <= day <= end_date:
                days.add(day)
    return sorted(days)


def _build_folds(request: HpoRequest, data_dir: Path) -> tuple[list[Any], dict[str, Any]]:
    base_request = request.base
    universe = build_universe_from_request(base_request, data_dir)
    execution_mode = str(base_request.execution.mode or "INTRADAY_MINUTE").upper()
    execution_model = str(base_request.execution.execution_model or "MINUTE_REPLAY").upper()

    dates: list[date] = []
    if execution_mode == "INTRADAY_MINUTE" and execution_model == "MINUTE_REPLAY":
        dates = _minute_calendar_dates(request=base_request, data_dir=data_dir, universe=universe)
    if not dates:
        data_store = HistoryDataStore(
            data_dir,
            universe,
            start_date=base_request.test.start_date,
            end_date=base_request.test.end_date,
        )
        dates = data_store.get_calendar(base_request.test.start_date, base_request.test.end_date)
    if not dates:
        raise ValueError("calendar_empty")
    total_days = len(dates)
    train_days, val_days, test_days, step_days = _resolve_fold_lengths(total_days, request)
    embargo_days = request.cv.embargo_days
    folds = build_walk_forward_folds(
        dates,
        train_days=train_days,
        val_days=val_days,
        test_days=test_days,
        step_days=step_days,
        embargo_days=embargo_days,
    )
    fallback_used = False
    if not folds:
        fallback_used = True
        train_days, val_days, test_days, step_days = _fallback_fold_lengths(total_days)
        embargo_days = 0
        folds = build_walk_forward_folds(
            dates,
            train_days=train_days,
            val_days=val_days,
            test_days=test_days,
            step_days=step_days,
            embargo_days=embargo_days,
        )
    if request.cv.folds and request.cv.folds > 0:
        folds = folds[: request.cv.folds]
    if not folds:
        raise ValueError("not_enough_data_for_folds")
    meta = {
        "train_days": train_days,
        "val_days": val_days,
        "test_days": test_days,
        "step_days": step_days,
        "embargo_days": embargo_days,
        "folds": len(folds),
        "fallback": fallback_used,
    }
    return folds, meta


def start_hpo_run(
    request: HpoRequest,
    data_dir: Path,
    *,
    run_id: str | None = None,
    precompute: bool | None = True,
    max_trials_override: int | None = None,
) -> dict[str, Any]:
    run_id = run_id or f"hpo-{uuid.uuid4().hex[:10]}"
    run_dir = _run_dir(data_dir, run_id)
    created_at = _iso_now()

    folds, folds_meta = _build_folds(request, data_dir)
    max_trials = max_trials_override or request.optimization.max_trials or DEFAULT_MAX_TRIALS
    max_trials = max(int(max_trials), 1)

    status_payload = {
        "run_id": run_id,
        "status": "running",
        "created_at": created_at,
        "started_at": created_at,
        "finished_at": None,
        "progress": {"completed": 0, "total": max_trials},
        "message": "HPO started",
    }
    _write_json(_status_path(run_dir), status_payload)

    metadata = {
        "run_id": run_id,
        "created_at": created_at,
        "request": request.model_dump(mode="python"),
        "folds": [_serialize_fold(fold) for fold in folds],
        "folds_meta": folds_meta,
        "max_trials": max_trials,
        "algorithm": DEFAULT_ALGORITHM,
        "aggregation": DEFAULT_AGGREGATION,
        "evaluation_mode": DEFAULT_EVALUATION,
        "precompute": precompute,
    }
    _write_json(run_dir / "run.json", metadata)
    _write_active_run(data_dir, run_id, created_at)

    thread = threading.Thread(
        target=_run_hpo_async,
        name=f"hpo-{run_id}",
        daemon=True,
        kwargs={
            "request": request,
            "folds": folds,
            "folds_meta": folds_meta,
            "data_dir": Path(data_dir),
            "run_dir": run_dir,
            "max_trials": max_trials,
            "precompute": precompute,
        },
    )
    thread.start()
    return status_payload


def load_hpo_status(data_dir: Path, *, run_id: str | None = None) -> dict[str, Any]:
    if run_id is None:
        run_id = _load_active_run(data_dir)
    if not run_id:
        raise ValueError("no_active_run")
    run_dir = _run_dir(data_dir, run_id)
    if not run_dir.exists():
        raise ValueError("run_not_found")
    status = _read_json(_status_path(run_dir)) or {}
    status.setdefault("run_id", run_id)
    if status.get("status") == "completed":
        result_payload = _read_json(_result_path(run_dir))
        if result_payload:
            status["result"] = result_payload
    return status


def _run_hpo_async(
    *,
    request: HpoRequest,
    folds: list[Any],
    folds_meta: dict[str, Any],
    data_dir: Path,
    run_dir: Path,
    max_trials: int,
    precompute: bool | None,
) -> None:
    status_path = _status_path(run_dir)
    status_seed = _read_json(status_path) or {}
    created_at = status_seed.get("created_at")
    started_at = status_seed.get("started_at")
    completed = 0
    try:
        rng = random.Random(request.optimization.random_seed)
        space = parse_search_space(request.search_space)
        mode = str(request.optimization.mode or "max").lower()
        if mode not in {"max", "min"}:
            mode = "max"
        metric = str(request.optimization.metric or "excess_ann")
        objective = ObjectiveConfig(metric=metric, mode=mode)
        trials: list[TrialResult] = []
        for idx in range(max_trials):
            if DEFAULT_ALGORITHM == "TPE":
                params = sample_tpe(space, trials, rng, mode=mode)
            else:
                params = sample_random(space, rng)
            trial = _evaluate_trial(
                base_request=request.base,
                params=params,
                folds=folds,
                data_dir=data_dir,
                objective=objective,
                aggregation=DEFAULT_AGGREGATION,
                evaluation_mode=DEFAULT_EVALUATION,
                precompute=precompute,
                backtest_runner=_default_backtest_runner,
            )
            trials.append(trial)
            completed = idx + 1
            _write_json(
                status_path,
                {
                    "run_id": run_dir.name,
                    "status": "running",
                    "created_at": created_at,
                    "started_at": started_at,
                    "finished_at": None,
                    "progress": {"completed": completed, "total": max_trials},
                    "message": "HPO running",
                },
            )
        result = HpoResult(trials=trials, mode=mode)
        quality_review = _build_quality_review(
            request=request,
            result=result,
            data_dir=data_dir,
            precompute=precompute,
        )
        result_payload = _serialize_result(result)
        if quality_review is not None:
            result_payload["quality_review"] = quality_review
        _write_json(_result_path(run_dir), result_payload)
        status_payload = {
            "run_id": run_dir.name,
            "status": "completed",
            "created_at": created_at,
            "started_at": started_at,
            "finished_at": _iso_now(),
            "progress": {"completed": max_trials, "total": max_trials},
            "message": "HPO completed",
            "folds_meta": folds_meta,
        }
        _write_json(status_path, status_payload)
    except Exception as exc:
        status_payload = {
            "run_id": run_dir.name,
            "status": "failed",
            "created_at": created_at,
            "started_at": started_at,
            "finished_at": _iso_now(),
            "progress": {"completed": completed, "total": max_trials},
            "message": "HPO failed",
            "error": str(exc),
        }
        _write_json(status_path, status_payload)
