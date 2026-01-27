from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from moex_carry.backtest_v2 import BacktestReport
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.data.history_store import HistoryDataStore
from moex_carry.domain.models import KeyRate
from moex_carry.hpo.types import AggregationMode, ObjectiveConfig

NEG_INF = float("-inf")


def compute_objective(metrics: Mapping[str, float], config: ObjectiveConfig) -> float:
    excess_ann = _excess_ann(metrics)
    max_dd = _normalize_drawdown(metrics.get("MaxDD"))
    avg_turnover = float(metrics.get("AvgTurnover") or 0.0)
    dd_limit = _normalize_drawdown(config.dd_max) if config.dd_max is not None else None
    to_limit = float(config.to_max) if config.to_max is not None else None
    if dd_limit is not None and max_dd > dd_limit:
        return NEG_INF
    if to_limit is not None and avg_turnover > to_limit:
        return NEG_INF
    penalty_dd = 0.0
    penalty_to = 0.0
    if dd_limit is not None:
        penalty_dd = config.lambda_dd * max(0.0, max_dd - dd_limit)
    if to_limit is not None:
        penalty_to = config.lambda_to * max(0.0, avg_turnover - to_limit)
    return excess_ann - penalty_dd - penalty_to


def aggregate_objectives(values: Iterable[float], mode: AggregationMode) -> float:
    values = list(values)
    if not values:
        return NEG_INF
    if any(not math.isfinite(value) for value in values):
        return NEG_INF
    if mode == "mean":
        return sum(values) / len(values)
    ordered = sorted(values)
    if mode == "median":
        return _percentile(ordered, 0.5)
    if mode == "p25":
        return _percentile(ordered, 0.25)
    raise ValueError(f"unknown aggregation mode: {mode}")


def compute_window_metrics(
    report: BacktestReport,
    start_date: date,
    end_date: date,
    data_dir: Path,
) -> dict[str, float]:
    curve = [point for point in report.equity_curve if start_date <= point.date <= end_date]
    if len(curve) < 2:
        return _empty_metrics()
    daily_returns = []
    benchmark_returns = []
    turnover_ratios = [point.turnover for point in curve]
    key_rates = _load_key_rates(data_dir)
    rate_cache = _build_rate_cache([point.date for point in curve], key_rates)
    resolved = report.resolved_config or {}
    for idx in range(1, len(curve)):
        prev_equity = curve[idx - 1].equity
        equity_value = curve[idx].equity
        daily_return = (equity_value / prev_equity - 1.0) if prev_equity > 0 else 0.0
        daily_returns.append(daily_return)
        benchmark_returns.append(_benchmark_daily_return(curve[idx].date, resolved, key_rates, rate_cache))
    trades = [
        trade
        for trade in report.trades
        if start_date <= trade.entry_date <= end_date and trade.exit_date <= end_date
    ]
    return _compute_metrics(
        equity_curve=curve,
        daily_returns=daily_returns,
        benchmark_returns=benchmark_returns,
        turnover_ratios=turnover_ratios,
        trades=trades,
        initial_equity=curve[0].equity,
    )


def _excess_ann(metrics: Mapping[str, float]) -> float:
    if "ExcessAnn" in metrics:
        return float(metrics.get("ExcessAnn") or 0.0)
    ex_d = metrics.get("ex_d")
    if ex_d is None:
        return 0.0
    return float(ex_d) * 252.0


def _normalize_drawdown(value: float | None) -> float:
    if value is None:
        return 0.0
    value = float(value)
    return abs(value)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return NEG_INF
    if len(values) == 1:
        return values[0]
    q = max(0.0, min(1.0, q))
    pos = (len(values) - 1) * q
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return values[lower]
    weight = pos - lower
    return values[lower] + (values[upper] - values[lower]) * weight


def _empty_metrics() -> dict[str, float]:
    return {
        "r_d": 0.0,
        "b_d": 0.0,
        "ex_d": 0.0,
        "CAGR": 0.0,
        "Vol_ann": 0.0,
        "IR": 0.0,
        "MaxDD": 0.0,
        "AvgTurnover": 0.0,
        "WinRate": 0.0,
        "ProfitFactor": 0.0,
        "AvgHoldDays": 0.0,
        "ShareAlphaExits": 0.0,
    }


def _compute_metrics(
    *,
    equity_curve: list[Any],
    daily_returns: list[float],
    benchmark_returns: list[float],
    turnover_ratios: list[float],
    trades: list[Any],
    initial_equity: float,
) -> dict[str, float]:
    equity_values = [point.equity for point in equity_curve]
    years = 0.0
    if len(equity_curve) >= 2:
        years = (equity_curve[-1].date - equity_curve[0].date).days / 365.0
    years = max(years, 1 / 365.0)
    equity_ratio = equity_values[-1] / initial_equity if initial_equity > 0 else 1.0
    cagr = equity_ratio ** (1.0 / years) - 1.0 if equity_ratio > 0 else 0.0

    r_d = _mean(daily_returns)
    b_d = _mean(benchmark_returns)
    excess_returns = [r - b for r, b in zip(daily_returns, benchmark_returns)]
    ex_d = _mean(excess_returns)

    vol_ann = _std(daily_returns) * (252.0**0.5)
    ir = 0.0
    if excess_returns:
        ex_std = _std(excess_returns)
        if ex_std > 0:
            ir = _mean(excess_returns) / ex_std * (252.0**0.5)

    max_dd = _max_drawdown(equity_values)
    avg_turnover = _mean(turnover_ratios)

    wins = [trade.pnl for trade in trades if trade.pnl > 0]
    losses = [trade.pnl for trade in trades if trade.pnl < 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    profit_factor = 0.0
    if wins and losses:
        profit_factor = sum(wins) / abs(sum(losses))
    elif wins and not losses:
        profit_factor = float("inf")

    avg_hold = _mean([trade.hold_days for trade in trades]) if trades else 0.0
    alpha_exits = 0
    alpha_exit_reasons = {"EXIT_TP", "EXIT_SL", "EXIT_TRAIL"}
    for trade in trades:
        if trade.exit_reason in alpha_exit_reasons:
            alpha_exits += 1
    share_alpha_exits = alpha_exits / len(trades) if trades else 0.0

    return {
        "r_d": float(r_d),
        "b_d": float(b_d),
        "ex_d": float(ex_d),
        "CAGR": float(cagr),
        "Vol_ann": float(vol_ann),
        "IR": float(ir),
        "MaxDD": float(max_dd),
        "AvgTurnover": float(avg_turnover),
        "WinRate": float(win_rate),
        "ProfitFactor": float(profit_factor),
        "AvgHoldDays": float(avg_hold),
        "ShareAlphaExits": float(share_alpha_exits),
    }


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    var = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return var**0.5


def _max_drawdown(equity_values: list[float]) -> float:
    if not equity_values:
        return 0.0
    peak = equity_values[0]
    max_dd = 0.0
    for value in equity_values:
        peak = max(peak, value)
        drawdown = value / peak - 1.0 if peak > 0 else 0.0
        max_dd = min(max_dd, drawdown)
    return max_dd


def _load_key_rates(data_dir: Path) -> list[KeyRate]:
    data_store = HistoryDataStore(Path(data_dir), pairs=[])
    return data_store.get_key_rates()


def _build_rate_cache(trading_days: Iterable[date], key_rates: list[KeyRate]) -> dict[date, KeyRate | None]:
    days = sorted(set(trading_days))
    if not days:
        return {}
    if not key_rates:
        return {day: None for day in days}
    sorted_rates = sorted(key_rates, key=lambda rate: rate.date)
    cache: dict[date, KeyRate | None] = {}
    idx = 0
    current: KeyRate | None = None
    for day in days:
        while idx < len(sorted_rates) and sorted_rates[idx].date <= day:
            current = sorted_rates[idx]
            idx += 1
        cache[day] = current
    return cache


def _resolve_key_rate(
    day: date,
    key_rates: list[KeyRate],
    rate_cache: Mapping[date, KeyRate | None] | None,
) -> KeyRate | None:
    if rate_cache is not None and day in rate_cache:
        return rate_cache[day]
    return latest_rate(key_rates, day)


def _benchmark_daily_return(
    day: date,
    resolved: Mapping[str, Any],
    key_rates: list[KeyRate],
    rate_cache: Mapping[date, KeyRate | None] | None,
) -> float:
    rates_cfg = resolved.get("rates", {}) if isinstance(resolved, Mapping) else {}
    day_count = str(rates_cfg.get("day_count") or "ACT/365")
    base = 360.0 if day_count.upper() == "ACT/360" else 365.0
    r_cb = rates_cfg.get("r_cb_annual")
    key_rate_row = _resolve_key_rate(day, key_rates, rate_cache)
    r_cb_value = float(r_cb) if r_cb is not None else float(key_rate_row.rate if key_rate_row else 0.0)
    return r_cb_value / base if base > 0 else 0.0
