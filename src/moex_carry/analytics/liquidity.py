from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class LiquidityMetrics:
    spread_bps_stock: Optional[float]
    spread_bps_fut: Optional[float]
    dollar_vol_stock: Optional[float]
    dollar_vol_fut: Optional[float]
    avg_dollar_vol: Optional[float]
    days_to_exit: Optional[float]
    open_interest: Optional[float]
    liquidity_pass: bool


def spread_bps(bid: Optional[float], ask: Optional[float], mid: Optional[float]) -> Optional[float]:
    if bid is None or ask is None or mid is None or mid == 0:
        return None
    return ((ask - bid) / mid) * 10000.0


def dollar_volume(price: Optional[float], volume: Optional[float], multiplier: float = 1.0) -> Optional[float]:
    if price is None or volume is None:
        return None
    return float(price) * float(volume) * float(multiplier)


def avg_dollar_volume(
    dollar_vol_stock: Optional[float],
    dollar_vol_fut: Optional[float],
) -> Optional[float]:
    if dollar_vol_stock is not None and dollar_vol_fut is not None:
        return min(float(dollar_vol_stock), float(dollar_vol_fut))
    return float(dollar_vol_stock) if dollar_vol_stock is not None else (
        float(dollar_vol_fut) if dollar_vol_fut is not None else None
    )


def days_to_exit(
    position_notional: Optional[float],
    avg_dollar_vol: Optional[float],
    participation_rate: Optional[float],
) -> Optional[float]:
    if (
        position_notional is None
        or avg_dollar_vol is None
        or participation_rate is None
        or avg_dollar_vol <= 0
        or participation_rate <= 0
    ):
        return None
    return float(position_notional) / (float(avg_dollar_vol) * float(participation_rate))


def evaluate_liquidity(
    spread_bps_stock_value: Optional[float],
    spread_bps_fut_value: Optional[float],
    dollar_vol_stock_value: Optional[float],
    dollar_vol_fut_value: Optional[float],
    open_interest: Optional[float],
    days_to_exit_value: Optional[float],
    max_spread_bps_stock: Optional[float] = None,
    max_spread_bps_fut: Optional[float] = None,
    min_dollar_vol_stock: Optional[float] = None,
    min_dollar_vol_fut: Optional[float] = None,
    min_open_interest: Optional[float] = None,
    max_days_to_exit: Optional[float] = None,
) -> bool:
    checks = []
    if max_spread_bps_stock is not None and spread_bps_stock_value is not None:
        checks.append(spread_bps_stock_value <= max_spread_bps_stock)
    if max_spread_bps_fut is not None and spread_bps_fut_value is not None:
        checks.append(spread_bps_fut_value <= max_spread_bps_fut)
    if min_dollar_vol_stock is not None and dollar_vol_stock_value is not None:
        checks.append(dollar_vol_stock_value >= min_dollar_vol_stock)
    if min_dollar_vol_fut is not None and dollar_vol_fut_value is not None:
        checks.append(dollar_vol_fut_value >= min_dollar_vol_fut)
    if min_open_interest is not None and open_interest is not None:
        checks.append(open_interest >= min_open_interest)
    if max_days_to_exit is not None and days_to_exit_value is not None:
        checks.append(days_to_exit_value <= max_days_to_exit)
    return all(checks) if checks else True


def compute_liquidity_metrics(
    spread_bps_stock_value: Optional[float],
    spread_bps_fut_value: Optional[float],
    dollar_vol_stock_value: Optional[float],
    dollar_vol_fut_value: Optional[float],
    open_interest: Optional[float],
    days_to_exit_value: Optional[float],
    max_spread_bps_stock: Optional[float] = None,
    max_spread_bps_fut: Optional[float] = None,
    min_dollar_vol_stock: Optional[float] = None,
    min_dollar_vol_fut: Optional[float] = None,
    min_open_interest: Optional[float] = None,
    max_days_to_exit: Optional[float] = None,
) -> LiquidityMetrics:
    avg_dollar = avg_dollar_volume(dollar_vol_stock_value, dollar_vol_fut_value)
    liquidity_pass = evaluate_liquidity(
        spread_bps_stock_value=spread_bps_stock_value,
        spread_bps_fut_value=spread_bps_fut_value,
        dollar_vol_stock_value=dollar_vol_stock_value,
        dollar_vol_fut_value=dollar_vol_fut_value,
        open_interest=open_interest,
        days_to_exit_value=days_to_exit_value,
        max_spread_bps_stock=max_spread_bps_stock,
        max_spread_bps_fut=max_spread_bps_fut,
        min_dollar_vol_stock=min_dollar_vol_stock,
        min_dollar_vol_fut=min_dollar_vol_fut,
        min_open_interest=min_open_interest,
        max_days_to_exit=max_days_to_exit,
    )
    return LiquidityMetrics(
        spread_bps_stock=spread_bps_stock_value,
        spread_bps_fut=spread_bps_fut_value,
        dollar_vol_stock=dollar_vol_stock_value,
        dollar_vol_fut=dollar_vol_fut_value,
        avg_dollar_vol=avg_dollar,
        days_to_exit=days_to_exit_value,
        open_interest=open_interest,
        liquidity_pass=liquidity_pass,
    )
