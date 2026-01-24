from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class SpreadMetrics:
    spread_mid: float
    spread_entry_exec: float
    spread_exit_exec: float
    spread_pct: float


def spread_mid(spot_mid: float, pv_div: float, fut_mid: float) -> float:
    return (spot_mid - pv_div) - fut_mid


def spread_entry_exec(spot_buy: float, pv_div: float, fut_sell: float) -> float:
    return (spot_buy - pv_div) - fut_sell


def spread_exit_exec(spot_sell: float, pv_div: float, fut_buy: float) -> float:
    return (spot_sell - pv_div) - fut_buy


def spread_pct(spread_value: float, spot_mid: Optional[float]) -> float:
    if spot_mid is None or spot_mid == 0:
        return 0.0
    return spread_value / spot_mid
