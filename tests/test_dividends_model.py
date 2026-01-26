from datetime import date

import math

import pytest

from moex_carry.analytics.dividends import div_sum, pv_dividends_exp
from moex_carry.domain.models import DividendEvent


def test_div_sum_filters_window():
    events = [
        DividendEvent(secid="AAA", ex_date=date(2025, 1, 5), amount=1.0, currency="RUB", status="forecast"),
        DividendEvent(secid="AAA", ex_date=date(2025, 2, 5), amount=2.0, currency="RUB", status="forecast"),
    ]
    total = div_sum(events, as_of=date(2025, 1, 10), expiry=date(2025, 2, 1))
    assert total == 0.0


def test_pv_dividends_exp_discount():
    events = [
        DividendEvent(secid="AAA", ex_date=date(2025, 1, 15), amount=10.0, currency="RUB", status="forecast"),
    ]
    pv = pv_dividends_exp(events, as_of=date(2025, 1, 1), expiry=date(2025, 2, 1), rate=0.1)
    assert pv < 10.0


def test_dividends_tau_known():
    events = [
        DividendEvent(secid="AAA", ex_date=date(2025, 1, 31), amount=10.0, currency="RUB", status="forecast"),
        DividendEvent(secid="AAA", ex_date=date(2025, 3, 2), amount=5.0, currency="RUB", status="forecast"),
    ]
    as_of = date(2025, 1, 1)
    expiry = date(2025, 4, 1)
    rate = 0.1
    pv = pv_dividends_exp(events, as_of=as_of, expiry=expiry, rate=rate, day_count="ACT/365")
    tau1 = 30 / 365
    tau2 = 60 / 365
    expected = 10.0 * math.exp(-rate * tau1) + 5.0 * math.exp(-rate * tau2)
    assert pv == pytest.approx(expected)
