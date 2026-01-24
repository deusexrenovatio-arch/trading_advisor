from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional


def _to_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def days_to_expiry(
    start: date | datetime,
    expiry: date | datetime,
    use_trading_days: bool = False,
    trading_days: Optional[Iterable[date]] = None,
) -> int:
    start_date = _to_date(start)
    expiry_date = _to_date(expiry)
    if use_trading_days and trading_days is not None:
        return sum(1 for day in trading_days if start_date < day <= expiry_date)
    delta = (expiry_date - start_date).days
    return max(delta, 0)


def year_fraction(
    start: date | datetime,
    end: date | datetime,
    day_count: str = "ACT/365",
) -> float:
    start_date = _to_date(start)
    end_date = _to_date(end)
    delta_days = (end_date - start_date).days
    if delta_days <= 0:
        return 0.0
    base = 360.0 if day_count.upper() == "ACT/360" else 365.0
    return delta_days / base
