from __future__ import annotations

from collections.abc import Sequence

from moex_carry.signal_engine.core.math_utils import clamp, round_half_away_from_zero


def mid_price(bid: float, ask: float) -> float:
    return (float(bid) + float(ask)) / 2.0


def spread_ticks(bid: float, ask: float, tick_size: float) -> int:
    if tick_size <= 0:
        raise ValueError("tick_size must be > 0")
    return max(round_half_away_from_zero((float(ask) - float(bid)) / float(tick_size)), 0)


def orderbook_imbalance(bid_sizes: Sequence[float], ask_sizes: Sequence[float], levels: int = 5) -> float:
    depth = max(int(levels), 1)
    bids = [max(float(value), 0.0) for value in bid_sizes[:depth]]
    asks = [max(float(value), 0.0) for value in ask_sizes[:depth]]
    bid_total = sum(bids)
    ask_total = sum(asks)
    denom = bid_total + ask_total
    if denom <= 0:
        return 0.0
    return float((bid_total - ask_total) / denom)


def is_liquidity_vacuum(
    *,
    spread_ticks_value: int | None,
    depth_lots: float | None,
    vacuum_spread_ticks: int,
    vacuum_depth_lots: float,
) -> bool:
    if spread_ticks_value is not None and int(spread_ticks_value) >= max(int(vacuum_spread_ticks), 0):
        return True
    if depth_lots is not None and float(depth_lots) <= max(float(vacuum_depth_lots), 0.0):
        return True
    return False


def depth_liquidity_penalty_ticks(
    *,
    depth_lots: float | None,
    depth_ref_lots: float,
    max_penalty_ticks: float,
    penalty_scale_ticks: float = 1.0,
    vacuum: bool = False,
) -> float:
    if vacuum:
        return float(max(max_penalty_ticks, 0.0))
    if depth_lots is None or depth_lots <= 0:
        return float(max(max_penalty_ticks, 0.0))
    ratio = (float(depth_ref_lots) / float(depth_lots)) - 1.0
    raw = max(ratio, 0.0) * max(float(penalty_scale_ticks), 0.0)
    return float(clamp(raw, 0.0, max(float(max_penalty_ticks), 0.0)))
