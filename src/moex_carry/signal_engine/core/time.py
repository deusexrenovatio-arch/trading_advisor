from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable


def within_forbid_window(
    ts: datetime,
    window_points: Iterable[datetime],
    *,
    forbid_minutes: int,
) -> bool:
    delta = timedelta(minutes=max(int(forbid_minutes), 0))
    for point in window_points:
        if abs(ts - point) <= delta:
            return True
    return False
