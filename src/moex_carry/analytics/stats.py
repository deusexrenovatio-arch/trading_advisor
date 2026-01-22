from __future__ import annotations

import math
from typing import Sequence

import numpy as np


def zscore(series: Sequence[float], window: int, min_window: int = 10) -> float:
    if window <= 1 or len(series) < min_window:
        return 0.0
    window = min(window, len(series))
    window_data = np.asarray(series[-window:])
    mean = float(window_data.mean())
    std = float(window_data.std(ddof=1))
    if std == 0:
        return 0.0
    return (float(window_data[-1]) - mean) / std


def spread_stats(series: Sequence[float], window: int, min_window: int = 10) -> dict[str, float]:
    if window <= 1:
        return {
            "window": 0.0,
            "mean": 0.0,
            "std": 0.0,
            "zscore": 0.0,
            "trend": 0.0,
            "trend_pos": 0.0,
            "trend_slope": 0.0,
            "trend_zscore": 0.0,
        }
    n = len(series)
    if n < min_window:
        return {
            "window": float(n),
            "mean": 0.0,
            "std": 0.0,
            "zscore": 0.0,
            "trend": 0.0,
            "trend_pos": 0.0,
            "trend_slope": 0.0,
            "trend_zscore": 0.0,
        }
    window = min(window, n)
    data = np.asarray(series[-window:], dtype=float)
    mean = float(data.mean())
    std = float(data.std(ddof=1)) if window > 1 else 0.0
    z = (float(data[-1]) - mean) / std if std > 0 else 0.0

    if window > 1:
        x = np.arange(window, dtype=float)
        slope, intercept = np.polyfit(x, data, 1)
        trend = intercept + slope * x
        residuals = data - trend
        resid_std = float(residuals.std(ddof=1)) if window > 1 else 0.0
        trend_z = float(residuals[-1]) / resid_std if resid_std > 0 else 0.0
        trend_last = float(trend[-1])
    else:
        slope = 0.0
        trend_last = float(data[-1])
        trend_z = 0.0

    return {
        "window": float(window),
        "mean": mean,
        "std": std,
        "zscore": z,
        "trend": trend_last,
        "trend_pos": float(data[-1] - trend_last),
        "trend_slope": float(slope),
        "trend_zscore": trend_z,
    }


def half_life(series: Sequence[float]) -> float:
    if len(series) < 2:
        return 0.0
    y = np.asarray(series[1:])
    x = np.asarray(series[:-1])
    x = x - x.mean()
    y = y - y.mean()
    beta = np.dot(x, y) / np.dot(x, x) if np.dot(x, x) != 0 else 0.0
    if beta >= 0:
        return 0.0
    return -math.log(2) / beta
