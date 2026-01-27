from __future__ import annotations

from datetime import date
from typing import Iterable

from moex_carry.hpo.types import WalkForwardFold


def build_walk_forward_folds(
    dates: Iterable[date],
    *,
    train_days: int,
    val_days: int,
    test_days: int,
    step_days: int,
    embargo_days: int = 0,
) -> list[WalkForwardFold]:
    ordered = sorted(set(dates))
    if train_days <= 0 or val_days <= 0 or test_days <= 0:
        raise ValueError("train_days, val_days, and test_days must be positive")
    if step_days <= 0:
        raise ValueError("step_days must be positive")
    if embargo_days < 0:
        raise ValueError("embargo_days must be non-negative")
    folds: list[WalkForwardFold] = []
    if not ordered:
        return folds
    start_idx = 0
    while True:
        train_start_idx = start_idx
        train_end_idx = train_start_idx + train_days - 1
        val_start_idx = train_end_idx + embargo_days + 1
        val_end_idx = val_start_idx + val_days - 1
        test_start_idx = val_end_idx + embargo_days + 1
        test_end_idx = test_start_idx + test_days - 1
        if test_end_idx >= len(ordered):
            break
        folds.append(
            WalkForwardFold(
                train_start=ordered[train_start_idx],
                train_end=ordered[train_end_idx],
                val_start=ordered[val_start_idx],
                val_end=ordered[val_end_idx],
                test_start=ordered[test_start_idx],
                test_end=ordered[test_end_idx],
            )
        )
        start_idx += step_days
    return folds
