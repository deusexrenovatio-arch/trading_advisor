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


def _synthetic_bid_ask(price: Optional[float], half_spread_bps: float) -> Optional[tuple[float, float]]:
    if price is None:
        return None
    base = float(price)
    half_spread = float(half_spread_bps) / 10000.0
    return base * (1.0 - half_spread), base * (1.0 + half_spread)


def _resolve_ohlc_bid_ask(
    ref_price: Optional[float],
    bid: Optional[float],
    ask: Optional[float],
    mid: Optional[float],
    half_spread_bps: float,
) -> tuple[float, float]:
    synthetic = _synthetic_bid_ask(ref_price, half_spread_bps)
    if synthetic is not None:
        return synthetic
    return _resolve_bid_ask(bid, ask, mid)


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


def _apply_fut_slip(
    price: float,
    side: str,
    slip_fut_bps: float,
    slip_fut_ticks: Optional[float],
    tick_size_fut: Optional[float],
) -> float:
    if slip_fut_ticks is not None and tick_size_fut is not None:
        return _apply_ticks(price, slip_fut_ticks, tick_size_fut, side)
    return _apply_bps(price, slip_fut_bps, side)


def build_execution_prices(
    stock_bid: Optional[float],
    stock_ask: Optional[float],
    fut_bid: Optional[float],
    fut_ask: Optional[float],
    stock_mid: Optional[float] = None,
    fut_mid: Optional[float] = None,
    stock_open: Optional[float] = None,
    stock_close: Optional[float] = None,
    fut_open: Optional[float] = None,
    fut_close: Optional[float] = None,
    mode: str = "BIDASK",
    half_spread_bps: float = 0.0,
    slip_stock_bps: float = 0.0,
    slip_fut_bps: float = 0.0,
    slip_fut_ticks: Optional[float] = None,
    tick_size_fut: Optional[float] = None,
) -> ExecutionPrices:
    mode_upper = (mode or "BIDASK").upper()
    if mode_upper == "OHLC":
        s_entry_bid, s_entry_ask = _resolve_ohlc_bid_ask(
            stock_open,
            stock_bid,
            stock_ask,
            stock_mid,
            half_spread_bps,
        )
        s_exit_bid, s_exit_ask = _resolve_ohlc_bid_ask(
            stock_close,
            stock_bid,
            stock_ask,
            stock_mid,
            half_spread_bps,
        )
        f_entry_bid, f_entry_ask = _resolve_ohlc_bid_ask(
            fut_open,
            fut_bid,
            fut_ask,
            fut_mid,
            half_spread_bps,
        )
        f_exit_bid, f_exit_ask = _resolve_ohlc_bid_ask(
            fut_close,
            fut_bid,
            fut_ask,
            fut_mid,
            half_spread_bps,
        )
        stock_buy = _apply_bps(s_entry_ask, slip_stock_bps, "buy")
        stock_sell = _apply_bps(s_exit_bid, slip_stock_bps, "sell")
        fut_sell = _apply_fut_slip(f_entry_bid, "sell", slip_fut_bps, slip_fut_ticks, tick_size_fut)
        fut_buy = _apply_fut_slip(f_exit_ask, "buy", slip_fut_bps, slip_fut_ticks, tick_size_fut)
    else:
        s_bid, s_ask = _resolve_bid_ask(stock_bid, stock_ask, stock_mid)
        f_bid, f_ask = _resolve_bid_ask(fut_bid, fut_ask, fut_mid)

        stock_buy = _apply_bps(s_ask, slip_stock_bps, "buy")
        stock_sell = _apply_bps(s_bid, slip_stock_bps, "sell")
        fut_sell = _apply_fut_slip(f_bid, "sell", slip_fut_bps, slip_fut_ticks, tick_size_fut)
        fut_buy = _apply_fut_slip(f_ask, "buy", slip_fut_bps, slip_fut_ticks, tick_size_fut)

    return ExecutionPrices(
        stock_buy=stock_buy,
        stock_sell=stock_sell,
        fut_sell=fut_sell,
        fut_buy=fut_buy,
    )
