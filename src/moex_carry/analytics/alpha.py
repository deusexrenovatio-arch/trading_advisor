from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

try:
    from numba import njit

    _HAS_NUMBA = True
except Exception:
    _HAS_NUMBA = False

    def njit(*args, **kwargs):  # type: ignore[override]
        def _wrap(func):
            return func

        return _wrap

MIN_HALFLIFE_POINTS = 10


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


def first_hit_probabilities(
    spread_pct: Sequence[float],
    horizon: int,
    tp: float,
    sl: float,
) -> tuple[float, float, float]:
    if horizon <= 0:
        return 0.0, 0.0, 0.0
    values = list(map(float, spread_pct))
    n = len(values)
    total = n - horizon
    if total <= 0:
        return 0.0, 0.0, 0.0
    eps = 1e-12
    tp_hits = 0
    sl_hits = 0
    none_hits = 0
    for idx in range(total):
        entry = values[idx]
        window = values[idx + 1 : idx + horizon + 1]
        tp_idx = None
        sl_idx = None
        for step_idx, value in enumerate(window):
            diff = value - entry
            if tp_idx is None and diff + eps >= tp:
                tp_idx = step_idx
            if sl_idx is None and diff - eps <= -sl:
                sl_idx = step_idx
            if tp_idx is not None and sl_idx is not None:
                break
        if tp_idx is None and sl_idx is None:
            none_hits += 1
            continue
        if sl_idx is None or (tp_idx is not None and tp_idx < sl_idx):
            tp_hits += 1
            continue
        # Tie goes to SL as conservative fallback for risk gating.
        sl_hits += 1
    denom = float(total)
    return float(tp_hits / denom), float(sl_hits / denom), float(none_hits / denom)


def round_trip_cost(
    stock_buy: float,
    stock_sell: float,
    fut_buy: float,
    fut_sell: float,
    fees_rt: float,
) -> float:
    return (stock_buy - stock_sell) + (fut_buy - fut_sell) + float(fees_rt)


def half_life_ar1(spread_pct: Sequence[float], min_points: int = MIN_HALFLIFE_POINTS) -> float:
    if len(spread_pct) < max(2, int(min_points)):
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


def alpha_matrices_fast(
    spread_pct: np.ndarray,
    *,
    horizon: int,
    tp: float,
    sl: float,
    history_days: int,
    min_points: int = MIN_HALFLIFE_POINTS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    series = np.asarray(spread_pct, dtype=float)
    if series.ndim != 2:
        raise ValueError("spread_pct must be 2D array [days, pairs]")
    if history_days <= 0:
        history_days = 1
    if _HAS_NUMBA:
        return _alpha_matrices_numba(series, horizon, tp, sl, history_days, min_points)
    return _alpha_matrices_numpy(series, horizon, tp, sl, history_days, min_points)


def alpha_has_numba() -> bool:
    return _HAS_NUMBA


@njit(cache=True)
def _alpha_matrices_numba(
    spread_pct: np.ndarray,
    horizon: int,
    tp: float,
    sl: float,
    history_days: int,
    min_points: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    d_count, p_count = spread_pct.shape
    p_hit_tp = np.zeros((d_count, p_count), dtype=np.float64)
    p_hit_sl = np.zeros((d_count, p_count), dtype=np.float64)
    sigma_h = np.zeros((d_count, p_count), dtype=np.float64)
    half_life = np.zeros((d_count, p_count), dtype=np.float64)
    eps = 1e-12

    for pair_idx in range(p_count):
        history = np.empty(history_days, dtype=np.float64)
        history_len = 0
        for day_idx in range(d_count):
            value = spread_pct[day_idx, pair_idx]
            if not np.isnan(value):
                if history_len < history_days:
                    history[history_len] = value
                    history_len += 1
                else:
                    for i in range(1, history_days):
                        history[i - 1] = history[i]
                    history[history_days - 1] = value

            if history_len > 0:
                sigma_h[day_idx, pair_idx] = _sigma_h(history, history_len, horizon)
                p_hit_tp[day_idx, pair_idx], p_hit_sl[day_idx, pair_idx] = _hit_probs(
                    history, history_len, horizon, tp, sl, eps
                )
                half_life[day_idx, pair_idx] = _half_life(history, history_len, min_points)
    return p_hit_tp, p_hit_sl, sigma_h, half_life


def _alpha_matrices_numpy(
    spread_pct: np.ndarray,
    horizon: int,
    tp: float,
    sl: float,
    history_days: int,
    min_points: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    d_count, p_count = spread_pct.shape
    p_hit_tp = np.zeros((d_count, p_count), dtype=float)
    p_hit_sl = np.zeros((d_count, p_count), dtype=float)
    sigma_h = np.zeros((d_count, p_count), dtype=float)
    half_life = np.zeros((d_count, p_count), dtype=float)
    eps = 1e-12

    for pair_idx in range(p_count):
        history = np.empty(history_days, dtype=float)
        history_len = 0
        for day_idx in range(d_count):
            value = spread_pct[day_idx, pair_idx]
            if not np.isnan(value):
                if history_len < history_days:
                    history[history_len] = float(value)
                    history_len += 1
                else:
                    history[:-1] = history[1:]
                    history[-1] = float(value)
            if history_len > 0:
                sigma_h[day_idx, pair_idx] = _sigma_h_py(history, history_len, horizon)
                p_hit_tp[day_idx, pair_idx], p_hit_sl[day_idx, pair_idx] = _hit_probs_py(
                    history, history_len, horizon, tp, sl, eps
                )
                half_life[day_idx, pair_idx] = _half_life_py(history, history_len, min_points)
    return p_hit_tp, p_hit_sl, sigma_h, half_life


@njit(cache=True)
def _sigma_h(values: np.ndarray, length: int, window: int) -> float:
    if window <= 1 or length < 2:
        return 0.0
    deltas_count = length - 1
    count = window if window < deltas_count else deltas_count
    if count <= 1:
        return 0.0
    start = length - count - 1
    mean = 0.0
    for i in range(start, length - 1):
        mean += values[i + 1] - values[i]
    mean /= count
    var = 0.0
    for i in range(start, length - 1):
        diff = (values[i + 1] - values[i]) - mean
        var += diff * diff
    var /= (count - 1)
    return np.sqrt(var)


@njit(cache=True)
def _hit_probs(
    values: np.ndarray,
    length: int,
    horizon: int,
    tp: float,
    sl: float,
    eps: float,
) -> tuple[float, float]:
    if horizon <= 0:
        return 0.0, 0.0
    total = length - horizon
    if total <= 0:
        return 0.0, 0.0
    hit_tp = 0.0
    hit_sl = 0.0
    for idx in range(total):
        entry = values[idx]
        max_diff = -1e30
        min_diff = 1e30
        end = idx + horizon
        for j in range(idx + 1, end + 1):
            diff = values[j] - entry
            if diff > max_diff:
                max_diff = diff
            if diff < min_diff:
                min_diff = diff
        if max_diff + eps >= tp:
            hit_tp += 1.0
        if min_diff - eps <= -sl:
            hit_sl += 1.0
    return hit_tp / total, hit_sl / total


@njit(cache=True)
def _half_life(values: np.ndarray, length: int, min_points: int) -> float:
    if length < min_points or length < 2:
        return 0.0
    x_len = length - 1
    mean_x = 0.0
    mean_y = 0.0
    for i in range(x_len):
        mean_x += values[i]
        mean_y += values[i + 1]
    mean_x /= x_len
    mean_y /= x_len
    num = 0.0
    den = 0.0
    for i in range(x_len):
        dx = values[i] - mean_x
        dy = values[i + 1] - mean_y
        num += dx * dy
        den += dx * dx
    if den <= 0.0:
        return 0.0
    slope = num / den
    if slope <= 0.0 or slope >= 1.0:
        return 0.0
    return math.log(2.0) / -math.log(slope)


def _sigma_h_py(values: np.ndarray, length: int, window: int) -> float:
    if window <= 1 or length < 2:
        return 0.0
    deltas_count = length - 1
    count = min(window, deltas_count)
    if count <= 1:
        return 0.0
    start = length - count - 1
    deltas = values[start + 1 : length] - values[start : length - 1]
    mean = float(np.mean(deltas))
    var = float(np.sum((deltas - mean) ** 2) / (count - 1))
    return float(np.sqrt(var))


def _hit_probs_py(
    values: np.ndarray,
    length: int,
    horizon: int,
    tp: float,
    sl: float,
    eps: float,
) -> tuple[float, float]:
    if horizon <= 0:
        return 0.0, 0.0
    total = length - horizon
    if total <= 0:
        return 0.0, 0.0
    hit_tp = 0.0
    hit_sl = 0.0
    for idx in range(total):
        entry = values[idx]
        window = values[idx + 1 : idx + horizon + 1]
        diffs = window - entry
        max_diff = float(np.max(diffs)) if diffs.size else -1e30
        min_diff = float(np.min(diffs)) if diffs.size else 1e30
        if max_diff + eps >= tp:
            hit_tp += 1.0
        if min_diff - eps <= -sl:
            hit_sl += 1.0
    return hit_tp / total, hit_sl / total


def _half_life_py(values: np.ndarray, length: int, min_points: int) -> float:
    if length < min_points or length < 2:
        return 0.0
    x = values[: length - 1]
    y = values[1:length]
    mean_x = float(np.mean(x))
    mean_y = float(np.mean(y))
    dx = x - mean_x
    dy = y - mean_y
    den = float(np.sum(dx * dx))
    if den <= 0.0:
        return 0.0
    slope = float(np.sum(dx * dy) / den)
    if slope <= 0.0 or slope >= 1.0:
        return 0.0
    return math.log(2.0) / -math.log(slope)
