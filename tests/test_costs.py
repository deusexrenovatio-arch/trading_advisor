from moex_carry.costs.engine import (
    CostProfile,
    costs_as_annual_rate,
    fut_fee_per_share,
    round_trip_fees,
    stock_fee_per_share,
    total_cost_bps,
)
from moex_carry.costs.taxes import TaxProfile, apply_dividend_tax, apply_profit_tax


def test_costs_as_rate():
    profile = CostProfile(1.0, 1.0, 0.5, 0.5)
    rate = costs_as_annual_rate(profile, time_years=0.5)
    assert rate > 0
    assert total_cost_bps(profile) == 3.0


def test_tax_application():
    tax_profile = TaxProfile(profit_tax_rate=0.13, dividend_tax_rate=0.13)
    assert apply_profit_tax(100.0, tax_profile) == 87.0
    assert apply_dividend_tax(100.0, tax_profile) == 87.0


def test_fee_models():
    stock_fee = stock_fee_per_share(price=100.0, fee_bps=10.0)
    assert stock_fee == 0.1
    stock_fee_fixed = stock_fee_per_share(price=100.0, fee_per_share=0.05)
    assert stock_fee_fixed == 0.05
    fut_fee = fut_fee_per_share(fee_per_contract=2.0, multiplier=10.0)
    assert fut_fee == 0.2
    assert round_trip_fees(stock_fee_fixed, fut_fee) == 0.5
