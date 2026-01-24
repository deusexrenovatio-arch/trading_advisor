from datetime import date

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
