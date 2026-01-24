from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np


@dataclass
class AlphaMetrics:
    sigma_h: float
    p_hit_tp: float
    p_hit_sl: float
    mfe_q50: float
    mfe_q75: float
    mfe_q90: float
    mae_q50: float
    mae_q75: float
    mae_q90: float
    half_life: float


def spread_volatility(spread_pct: Sequence[float], window: int) -> float:
    if window <= 1 or len(spread_pct) < 2:
        return 0.0
    deltas = np.diff(np.asarray(spread_pct, dtype=float))
    if len(deltas) == 0:
        return 0.0
    window = min(window, len(deltas))
    window_data = deltas[-window:]
    return float(np.std(window_data, ddof=1)) if window_data.size > 1 else 0.0


def mfe_mae(spread_pct: Sequence[float], horizon: int) -> tuple[list[float], list[float]]:
    if horizon <= 0:
        return [], []
    values = list(map(float, spread_pct))
    n = len(values)
    mfe_list: list[float] = []
    mae_list: list[float] = []
    for idx in range(n - horizon):
        entry = values[idx]
        window = values[idx + 1 : idx + horizon + 1]
        diffs = [value - entry for value in window]
        mfe_list.append(max(diffs))
        mae_list.append(min(diffs))
    return mfe_list, mae_list


def hit_probabilities(
    spread_pct: Sequence[float],
    horizon: int,
    tp: float,
    sl: float,
) -> tuple[float, float]:
    mfe_list, mae_list = mfe_mae(spread_pct, horizon)
    if not mfe_list:
        return 0.0, 0.0
    eps = 1e-12
    hit_tp = [1.0 if mfe + eps >= tp else 0.0 for mfe in mfe_list]
    hit_sl = [1.0 if mae - eps <= -sl else 0.0 for mae in mae_list]
    return float(np.mean(hit_tp)), float(np.mean(hit_sl))


def round_trip_cost(
    stock_buy: float,
    stock_sell: float,
    fut_buy: float,
    fut_sell: float,
    fees_rt: float,
) -> float:
    return (stock_buy - stock_sell) + (fut_buy - fut_sell) + float(fees_rt)


def half_life_ar1(spread_pct: Sequence[float]) -> float:
    if len(spread_pct) < 2:
        return 0.0
    x = np.asarray(spread_pct[:-1], dtype=float)
    y = np.asarray(spread_pct[1:], dtype=float)
    if x.size < 2:
        return 0.0
    slope, _ = np.polyfit(x, y, 1)
    if slope <= 0 or slope >= 1:
        return 0.0
    return math.log(2.0) / -math.log(slope)


def alpha_metrics(
    spread_pct: Sequence[float],
    horizon: int,
    tp: float,
    sl: float,
) -> AlphaMetrics:
    sigma_h = spread_volatility(spread_pct, window=horizon)
    p_hit_tp, p_hit_sl = hit_probabilities(spread_pct, horizon, tp, sl)
    mfe_list, mae_list = mfe_mae(spread_pct, horizon)
    mfe_q50 = float(np.quantile(mfe_list, 0.5)) if mfe_list else 0.0
    mfe_q75 = float(np.quantile(mfe_list, 0.75)) if mfe_list else 0.0
    mfe_q90 = float(np.quantile(mfe_list, 0.9)) if mfe_list else 0.0
    mae_q50 = float(np.quantile(mae_list, 0.5)) if mae_list else 0.0
    mae_q75 = float(np.quantile(mae_list, 0.75)) if mae_list else 0.0
    mae_q90 = float(np.quantile(mae_list, 0.9)) if mae_list else 0.0
    half_life = half_life_ar1(spread_pct)
    return AlphaMetrics(
        sigma_h=sigma_h,
        p_hit_tp=p_hit_tp,
        p_hit_sl=p_hit_sl,
        mfe_q50=mfe_q50,
        mfe_q75=mfe_q75,
        mfe_q90=mfe_q90,
        mae_q50=mae_q50,
        mae_q75=mae_q75,
        mae_q90=mae_q90,
        half_life=half_life,
    )
