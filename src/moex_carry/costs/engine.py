from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostProfile:
    stock_commission_bps: float
    futures_commission_bps: float
    exchange_fee_bps: float
    slippage_bps: float


def total_cost_bps(profile: CostProfile) -> float:
    return (
        profile.stock_commission_bps
        + profile.futures_commission_bps
        + profile.exchange_fee_bps
        + profile.slippage_bps
    )


def costs_as_annual_rate(profile: CostProfile, time_years: float) -> float:
    if time_years <= 0:
        return 0.0
    return total_cost_bps(profile) / 10000.0 / time_years
