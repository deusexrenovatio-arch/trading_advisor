from __future__ import annotations

import math


def round_half_away_from_zero(value: float) -> int:
    if value >= 0.0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def price_to_ticks(price: float, tick_size: float) -> int:
    if tick_size <= 0:
        raise ValueError("tick_size must be > 0")
    return round_half_away_from_zero(float(price) / float(tick_size))


def ticks_to_price(ticks: int, tick_size: float) -> float:
    if tick_size <= 0:
        raise ValueError("tick_size must be > 0")
    return float(ticks) * float(tick_size)


def clamp(value: float, lower: float, upper: float) -> float:
    if lower > upper:
        raise ValueError("lower must be <= upper")
    return float(min(max(value, lower), upper))


def normalize_three_way_probabilities(
    p_tp: float,
    p_sl: float,
    p_exit: float,
    *,
    epsilon: float = 1e-12,
) -> tuple[float, float, float]:
    total = float(p_tp) + float(p_sl) + float(p_exit)
    if not math.isfinite(total) or total <= epsilon:
        return (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)
    p_tp_norm = max(float(p_tp), 0.0) / total
    p_sl_norm = max(float(p_sl), 0.0) / total
    p_exit_norm = max(float(p_exit), 0.0) / total
    final_total = p_tp_norm + p_sl_norm + p_exit_norm
    if final_total <= epsilon:
        return (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)
    return (
        float(p_tp_norm / final_total),
        float(p_sl_norm / final_total),
        float(p_exit_norm / final_total),
    )
