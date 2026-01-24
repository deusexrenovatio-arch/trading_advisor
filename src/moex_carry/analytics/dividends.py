from __future__ import annotations

import math
from datetime import date
from typing import Iterable

from moex_carry.analytics.time import year_fraction
from moex_carry.domain.models import DividendEvent


def div_sum(dividends: Iterable[DividendEvent], as_of: date, expiry: date) -> float:
    total = 0.0
    for event in dividends:
        if event.ex_date <= as_of or event.ex_date > expiry:
            continue
        total += float(event.amount)
    return total


def pv_dividends_exp(
    dividends: Iterable[DividendEvent],
    as_of: date,
    expiry: date,
    rate: float,
    day_count: str = "ACT/365",
) -> float:
    pv = 0.0
    for event in dividends:
        if event.ex_date <= as_of or event.ex_date > expiry:
            continue
        tau = year_fraction(as_of, event.ex_date, day_count)
        if tau <= 0:
            continue
        pv += float(event.amount) * math.exp(-rate * tau)
    return pv
