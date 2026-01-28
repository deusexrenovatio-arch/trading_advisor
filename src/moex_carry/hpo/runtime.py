from __future__ import annotations

import json
import random
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from moex_carry.backtest_v2.runtime import build_universe_from_request
from moex_carry.contracts.strategy_test import HpoRequest
from moex_carry.data.history_store import HistoryDataStore
from moex_carry.hpo.folds import build_walk_forward_folds
from moex_carry.hpo.objective import ObjectiveConfig
from moex_carry.hpo.runner import _default_backtest_runner, _evaluate_trial
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
    }


def _serialize_result(result: HpoResult) -> dict[str, Any]:
    trials = [_serialize_trial(trial) for trial in result.trials]
    leaderboard = [_serialize_trial(trial) for trial in result.leaderboard()]
    return {
        "mode": result.mode,
        "trials": trials,
        "leaderboard": leaderboard,
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


def _build_folds(request: HpoRequest, data_dir: Path) -> tuple[list[Any], dict[str, Any]]:
    base_request = request.base
    universe = build_universe_from_request(base_request, data_dir)
    data_store = HistoryDataStore(
        data_dir,
        universe,
        start_date=base_request.test.start_date,
        end_date=base_request.test.end_date,
    )
    dates = data_store.get_calendar(base_request.test.start_date, base_request.test.end_date)
    if not dates:
        raise ValueError("calendar_empty")
    train_days, val_days, test_days, step_days = _resolve_fold_lengths(len(dates), request)
    folds = build_walk_forward_folds(
        dates,
        train_days=train_days,
        val_days=val_days,
        test_days=test_days,
        step_days=step_days,
        embargo_days=request.cv.embargo_days,
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
        "embargo_days": request.cv.embargo_days,
        "folds": len(folds),
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
    try:
        rng = random.Random(request.optimization.random_seed)
        space = parse_search_space(request.search_space)
        objective = ObjectiveConfig()
        trials: list[TrialResult] = []
        for idx in range(max_trials):
            if DEFAULT_ALGORITHM == "TPE":
                params = sample_tpe(space, trials, rng, mode="max")
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
            _write_json(
                status_path,
                {
                    "run_id": run_dir.name,
                    "status": "running",
                    "created_at": _read_json(status_path).get("created_at") if _read_json(status_path) else None,
                    "started_at": _read_json(status_path).get("started_at") if _read_json(status_path) else None,
                    "finished_at": None,
                    "progress": {"completed": idx + 1, "total": max_trials},
                    "message": "HPO running",
                },
            )
        result = HpoResult(trials=trials, mode="max")
        _write_json(_result_path(run_dir), _serialize_result(result))
        status_payload = {
            "run_id": run_dir.name,
            "status": "completed",
            "created_at": _read_json(status_path).get("created_at") if _read_json(status_path) else None,
            "started_at": _read_json(status_path).get("started_at") if _read_json(status_path) else None,
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
            "created_at": _read_json(status_path).get("created_at") if _read_json(status_path) else None,
            "started_at": _read_json(status_path).get("started_at") if _read_json(status_path) else None,
            "finished_at": _iso_now(),
            "progress": {"completed": 0, "total": max_trials},
            "message": "HPO failed",
            "error": str(exc),
        }
        _write_json(status_path, status_payload)
