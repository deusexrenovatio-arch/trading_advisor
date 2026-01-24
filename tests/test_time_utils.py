from datetime import date

from moex_carry.analytics.time import days_to_expiry, year_fraction


def test_days_to_expiry_calendar():
    start = date(2025, 1, 1)
    expiry = date(2025, 1, 11)
    assert days_to_expiry(start, expiry) == 10


def test_days_to_expiry_trading_days():
    start = date(2025, 1, 1)
    expiry = date(2025, 1, 6)
    trading_days = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6)]
    assert days_to_expiry(start, expiry, use_trading_days=True, trading_days=trading_days) == 3


def test_year_fraction_act365():
    start = date(2025, 1, 1)
    end = date(2025, 1, 31)
    assert year_fraction(start, end, "ACT/365") == 30 / 365.0


def test_year_fraction_act360():
    start = date(2025, 1, 1)
    end = date(2025, 1, 31)
    assert year_fraction(start, end, "ACT/360") == 30 / 360.0
