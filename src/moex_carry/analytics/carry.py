from __future__ import annotations

import math
from datetime import date
from typing import Iterable

from moex_carry.domain.models import DividendEvent


def pv_dividends(
    dividends: Iterable[DividendEvent], as_of: date, expiry: date, rate: float
) -> float:
    pv = 0.0
    for event in dividends:
        if event.ex_date <= as_of or event.ex_date > expiry:
            continue
        t = (event.ex_date - as_of).days / 365.0
        if t <= 0:
            continue
        pv += event.amount * math.exp(-rate * t)
    return pv


def fair_value(spot: float, pv_div: float, funding_rate: float, time_years: float) -> float:
    return (spot - pv_div) * (1 + funding_rate * time_years)


def implied_rate(future_price: float, spot: float, pv_div: float, time_years: float) -> float:
    if time_years <= 0 or spot <= 0:
        return 0.0
    return (future_price + pv_div - spot) / (spot * time_years)


def basis(future_price: float, fair_price: float) -> float:
    return future_price - fair_price
