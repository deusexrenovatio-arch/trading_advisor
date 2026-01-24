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


def stock_fee_per_share(
    price: float,
    fee_per_share: float | None = None,
    fee_bps: float | None = None,
) -> float:
    if fee_per_share is not None:
        return float(fee_per_share)
    if fee_bps is not None:
        return float(price) * float(fee_bps) / 10000.0
    return 0.0


def fut_fee_per_share(fee_per_contract: float, multiplier: float) -> float:
    if multiplier == 0:
        return 0.0
    return float(fee_per_contract) / float(multiplier)


def round_trip_fees(stock_fee: float, fut_fee: float) -> float:
    return 2.0 * (float(stock_fee) + float(fut_fee))
