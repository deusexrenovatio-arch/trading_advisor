from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd


@dataclass
class BacktestMetrics:
    cagr: float
    max_drawdown: float
    sharpe: float
    hit_rate: float
    turnover: float


def _max_drawdown(equity: pd.Series) -> float:
    rolling_max = equity.cummax()
    drawdown = equity / rolling_max - 1.0
    return float(drawdown.min()) if not drawdown.empty else 0.0


def compute_metrics(equity: pd.Series, trade_returns: list[float]) -> BacktestMetrics:
    if equity.empty:
        return BacktestMetrics(0.0, 0.0, 0.0, 0.0, 0.0)
    total_years = (equity.index[-1] - equity.index[0]).days / 365.0
    total_years = max(total_years, 1 / 365.0)
    cagr = equity.iloc[-1] ** (1 / total_years) - 1
    returns = equity.pct_change().dropna()
    sharpe = 0.0
    if not returns.empty and returns.std() != 0:
        sharpe = (returns.mean() / returns.std()) * math.sqrt(252)
    hit_rate = (
        sum(1 for r in trade_returns if r > 0) / len(trade_returns) if trade_returns else 0.0
    )
    turnover = len(trade_returns) / total_years
    return BacktestMetrics(
        cagr=float(cagr),
        max_drawdown=_max_drawdown(equity),
        sharpe=float(sharpe),
        hit_rate=float(hit_rate),
        turnover=float(turnover),
    )
