from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable


@dataclass
class WalkForwardSplit:
    train_start: date
    train_end: date
    test_start: date
    test_end: date


def walk_forward_splits(
    dates: Iterable[date], train_days: int, test_days: int, step_days: int
) -> list[WalkForwardSplit]:
    ordered = sorted(set(dates))
    splits: list[WalkForwardSplit] = []
    if not ordered:
        return splits
    start_idx = 0
    while start_idx + train_days + test_days <= len(ordered):
        train_start = ordered[start_idx]
        train_end = ordered[start_idx + train_days - 1]
        test_start = ordered[start_idx + train_days]
        test_end = ordered[start_idx + train_days + test_days - 1]
        splits.append(
            WalkForwardSplit(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        start_idx += step_days
    return splits
