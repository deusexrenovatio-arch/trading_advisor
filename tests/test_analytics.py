from datetime import date

from moex_carry.analytics.carry import fair_value, implied_rate, pv_dividends
from moex_carry.analytics.rates import target_annual_rate
from moex_carry.domain.models import DividendEvent


def test_pv_dividends_discounted():
    events = [
        DividendEvent(secid="SBER", ex_date=date(2025, 1, 15), amount=10.0, currency="RUB", status="forecast")
    ]
    pv = pv_dividends(events, as_of=date(2025, 1, 1), expiry=date(2025, 2, 1), rate=0.1)
    assert pv < 10.0


def test_implied_rate_basic():
    rate = implied_rate(future_price=105, spot=100, pv_div=0, time_years=0.5)
    assert rate > 0


def test_fair_value():
    fv = fair_value(spot=100, pv_div=2, funding_rate=0.1, time_years=0.5)
    assert fv > 0


def test_target_annual_rate_monotonic():
    r1 = target_annual_rate(0.1, 0.0, 0.01, 0.02, 0.25)
    r2 = target_annual_rate(0.1, 0.0, 0.01, 0.02, 0.75)
    assert r2 > r1
