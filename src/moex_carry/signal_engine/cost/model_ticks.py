from __future__ import annotations

from dataclasses import dataclass

from moex_carry.signal_engine.core.types import OutcomeForecast
from moex_carry.signal_engine.features.orderflow import depth_liquidity_penalty_ticks


@dataclass(frozen=True)
class TickCostModelConfig:
    commission_ticks_per_side: float = 0.5
    slippage_ticks_per_side: float = 1.0
    spread_half_ticks_fallback: float = 1.0
    depth_ref_lots: float = 100.0
    max_penalty_ticks: float = 2.0
    penalty_scale_ticks: float = 1.0


def round_trip_cost_ticks(
    *,
    spread_ticks_value: int | None = None,
    depth_lots: float | None = None,
    vacuum: bool = False,
    config: TickCostModelConfig = TickCostModelConfig(),
) -> float:
    spread_half = (
        max(float(spread_ticks_value), 0.0) / 2.0
        if spread_ticks_value is not None
        else max(float(config.spread_half_ticks_fallback), 0.0)
    )
    liquidity_penalty = depth_liquidity_penalty_ticks(
        depth_lots=depth_lots,
        depth_ref_lots=float(config.depth_ref_lots),
        max_penalty_ticks=float(config.max_penalty_ticks),
        penalty_scale_ticks=float(config.penalty_scale_ticks),
        vacuum=vacuum,
    )
    base = 2.0 * (
        max(float(config.commission_ticks_per_side), 0.0)
        + max(float(config.slippage_ticks_per_side), 0.0)
        + spread_half
    )
    return float(base + liquidity_penalty)


def expected_return_ticks(
    *,
    forecast: OutcomeForecast,
    tp_ticks: int,
    sl_ticks: int,
    cost_ticks: float,
    exit_return_ticks: float = 0.0,
) -> float:
    normalized = forecast.normalized()
    r_tp = float(max(int(tp_ticks), 0))
    r_sl = -float(max(int(sl_ticks), 0))
    r_exit = float(exit_return_ticks)
    expectancy = (
        normalized.p_tp * r_tp
        + normalized.p_sl * r_sl
        + normalized.p_exit * r_exit
    )
    return float(expectancy - float(cost_ticks))
