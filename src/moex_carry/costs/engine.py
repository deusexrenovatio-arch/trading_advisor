from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CostProfile:
    stock_commission_bps: float
    futures_commission_bps: float
    exchange_fee_bps: float
    slippage_bps: float


@dataclass
class RtcMetrics:
    fee_stock: float
    fee_fut: float
    fees_rt: float
    rtc: float
    rtc_pct: float


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


def fee_stock_from_config(
    spot_mid: float,
    costs_config: dict[str, Any],
) -> float:
    fee_per_share = costs_config.get("fee_stock_per_share")
    fee_bps = costs_config.get("fee_stock_bps")
    return stock_fee_per_share(
        spot_mid,
        fee_per_share=fee_per_share,
        fee_bps=fee_bps,
    )


def fee_fut_from_config(
    multiplier: float,
    costs_config: dict[str, Any],
) -> float:
    fee_per_contract = costs_config.get("fee_fut_per_contract")
    return fut_fee_per_share(float(fee_per_contract or 0.0), multiplier)


def compute_rtc(
    stock_buy: float,
    stock_sell: float,
    fut_buy: float,
    fut_sell: float,
    spot_mid: float,
    multiplier: float,
    costs_config: dict[str, Any],
) -> RtcMetrics:
    fee_stock = fee_stock_from_config(spot_mid, costs_config)
    fee_fut = fee_fut_from_config(multiplier, costs_config)
    fees_rt = round_trip_fees(fee_stock, fee_fut)
    rtc = (float(stock_buy) - float(stock_sell)) + (float(fut_buy) - float(fut_sell)) + float(fees_rt)
    rtc_pct = rtc / float(spot_mid) if spot_mid else 0.0
    return RtcMetrics(
        fee_stock=fee_stock,
        fee_fut=fee_fut,
        fees_rt=fees_rt,
        rtc=rtc,
        rtc_pct=rtc_pct,
    )
