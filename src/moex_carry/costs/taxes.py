from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TaxProfile:
    profit_tax_rate: float
    dividend_tax_rate: float


def apply_profit_tax(pnl: float, profile: TaxProfile) -> float:
    if pnl <= 0:
        return pnl
    return pnl * (1 - profile.profit_tax_rate)


def apply_dividend_tax(amount: float, profile: TaxProfile) -> float:
    return amount * (1 - profile.dividend_tax_rate)
