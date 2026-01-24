from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionPrices:
    stock_buy: float
    stock_sell: float
    fut_sell: float
    fut_buy: float


def _resolve_bid_ask(
    bid: Optional[float],
    ask: Optional[float],
    mid: Optional[float],
) -> tuple[float, float]:
    if bid is None and ask is None and mid is None:
        raise ValueError("Missing bid/ask/mid for execution pricing")
    if bid is None:
        bid = mid if mid is not None else ask
    if ask is None:
        ask = mid if mid is not None else bid
    if bid is None or ask is None:
        raise ValueError("Unable to resolve bid/ask for execution pricing")
    return float(bid), float(ask)


def _apply_bps(price: float, bps: float, side: str) -> float:
    if bps == 0:
        return price
    adj = bps / 10000.0
    if side == "buy":
        return price * (1.0 + adj)
    return price * (1.0 - adj)


def _apply_ticks(price: float, ticks: float, tick_size: float, side: str) -> float:
    if ticks == 0 or tick_size == 0:
        return price
    delta = ticks * tick_size
    if side == "buy":
        return price + delta
    return price - delta


def build_execution_prices(
    stock_bid: Optional[float],
    stock_ask: Optional[float],
    fut_bid: Optional[float],
    fut_ask: Optional[float],
    stock_mid: Optional[float] = None,
    fut_mid: Optional[float] = None,
    slip_stock_bps: float = 0.0,
    slip_fut_bps: float = 0.0,
    slip_fut_ticks: Optional[float] = None,
    tick_size_fut: Optional[float] = None,
) -> ExecutionPrices:
    s_bid, s_ask = _resolve_bid_ask(stock_bid, stock_ask, stock_mid)
    f_bid, f_ask = _resolve_bid_ask(fut_bid, fut_ask, fut_mid)

    stock_buy = _apply_bps(s_ask, slip_stock_bps, "buy")
    stock_sell = _apply_bps(s_bid, slip_stock_bps, "sell")

    if slip_fut_ticks is not None and tick_size_fut is not None:
        fut_sell = _apply_ticks(f_bid, slip_fut_ticks, tick_size_fut, "sell")
        fut_buy = _apply_ticks(f_ask, slip_fut_ticks, tick_size_fut, "buy")
    else:
        fut_sell = _apply_bps(f_bid, slip_fut_bps, "sell")
        fut_buy = _apply_bps(f_ask, slip_fut_bps, "buy")

    return ExecutionPrices(
        stock_buy=stock_buy,
        stock_sell=stock_sell,
        fut_sell=fut_sell,
        fut_buy=fut_buy,
    )
