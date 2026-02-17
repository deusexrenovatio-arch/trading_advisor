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

INVALID_OBJECTIVE = 1e12
NEG_INF = -INVALID_OBJECTIVE


def invalid_objective(mode: str) -> float:
    return NEG_INF if str(mode).lower() == "max" else INVALID_OBJECTIVE


def compute_objective(metrics: Mapping[str, float], config: ObjectiveConfig) -> float:
    if str(config.scope or "PORTFOLIO").upper() == "PORTFOLIO":
        return _compute_portfolio_objective(metrics, config)

    metric_value = _metric_value(metrics, config.metric)
    if not math.isfinite(metric_value):
        return invalid_objective(config.mode)
    max_dd = _normalize_drawdown(metrics.get("MaxDD"))
    avg_turnover = float(metrics.get("AvgTurnover") or 0.0)
    dd_limit = _normalize_drawdown(config.dd_max) if config.dd_max is not None else None
    to_limit = float(config.to_max) if config.to_max is not None else None
    if dd_limit is not None and max_dd > dd_limit:
        return invalid_objective(config.mode)
    if to_limit is not None and avg_turnover > to_limit:
        return invalid_objective(config.mode)
    penalty_dd = 0.0
    penalty_to = 0.0
    if dd_limit is not None:
        penalty_dd = config.lambda_dd * max(0.0, max_dd - dd_limit)
    if to_limit is not None:
        penalty_to = config.lambda_to * max(0.0, avg_turnover - to_limit)
    if str(config.mode).lower() == "min":
        return metric_value + penalty_dd + penalty_to
    return metric_value - penalty_dd - penalty_to


def _compute_portfolio_objective(metrics: Mapping[str, float], config: ObjectiveConfig) -> float:
    max_dd = abs(float(metrics.get("PortfolioMaxDD", metrics.get("MaxDD", 0.0)) or 0.0))
    idle_ratio = float(metrics.get("PortfolioIdleRatio", 0.0) or 0.0)
    forced_exit_rate = float(metrics.get("PortfolioForcedExitRate", 0.0) or 0.0)
    unfilled_entry_rate = float(metrics.get("PortfolioUnfilledEntryRate", 0.0) or 0.0)
    turnover = float(metrics.get("PortfolioTurnover", metrics.get("AvgTurnover", 0.0)) or 0.0)

    hard_max_dd = _none_or_float(config.hard_max_dd)
    hard_max_idle = _none_or_float(config.hard_max_idle_ratio)
    hard_max_forced = _none_or_float(config.hard_max_forced_exit_rate)
    hard_max_unfilled = _none_or_float(config.hard_max_unfilled_entry_rate)

    if hard_max_dd is not None and max_dd > hard_max_dd:
        return invalid_objective(config.mode)
    if hard_max_idle is not None and idle_ratio > hard_max_idle:
        return invalid_objective(config.mode)
    if hard_max_forced is not None and forced_exit_rate > hard_max_forced:
        return invalid_objective(config.mode)
    if hard_max_unfilled is not None and unfilled_entry_rate > hard_max_unfilled:
        return invalid_objective(config.mode)

    metric_key = str(config.portfolio_metric or "utility").lower()
    if metric_key == "cagr":
        base = float(metrics.get("PortfolioCAGR", metrics.get("CAGR", 0.0)) or 0.0)
    else:
        base = float(metrics.get("PortfolioExcessAnn", metrics.get("ExcessAnn", 0.0)) or 0.0)
    if not math.isfinite(base):
        return invalid_objective(config.mode)

    dd_soft_limit = abs(float(config.dd_soft_limit))
    penalty = 0.0
    penalty += float(config.lambda_dd) * max(0.0, max_dd - dd_soft_limit)
    penalty += float(config.lambda_idle) * idle_ratio
    penalty += float(config.lambda_forced) * forced_exit_rate
    penalty += float(config.lambda_unfilled) * unfilled_entry_rate
    penalty += float(config.lambda_turnover) * turnover

    score = base - penalty
    if metric_key == "utility":
        objective = score
    else:
        objective = base
    if str(config.mode).lower() == "min":
        return -objective
    return objective


def aggregate_objectives(
    values: Iterable[float],
    mode: AggregationMode,
    *,
    objective_mode: str = "max",
) -> float:
    values = list(values)
    if not values:
        return invalid_objective(objective_mode)
    if any(not math.isfinite(value) for value in values):
        return invalid_objective(objective_mode)
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
    rates_cfg = resolved.get("rates", {}) if isinstance(resolved, Mapping) else {}
    use_trading_days = bool(rates_cfg.get("use_trading_days"))
    annualization_days = 252.0 if use_trading_days else 365.0
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
        annualization_days=annualization_days,
    )


def _excess_ann(metrics: Mapping[str, float]) -> float:
    if "ExcessAnn" in metrics:
        return float(metrics.get("ExcessAnn") or 0.0)
    ex_d = metrics.get("ex_d")
    if ex_d is None:
        return 0.0
    annualization = float(metrics.get("AnnualizationDays") or 252.0)
    return float(ex_d) * annualization


def _metric_value(metrics: Mapping[str, float], metric: str | None) -> float:
    key = (metric or "excess_ann").strip().lower()
    if key in {"excessann", "excess_ann", "excess"}:
        return _excess_ann(metrics)
    if key in {"minute_excess_ann", "minute_excess_annual", "excess_annual_vs_target"}:
        return float(
            metrics.get("MinuteExcessAnnMean")
            or metrics.get("excess_annual_vs_target")
            or metrics.get("ExcessAnn")
            or 0.0
        )
    if key in {"realized_annualized_return", "minute_realized_annual", "minute_cagr"}:
        return float(
            metrics.get("MinuteRealizedAnnualMean")
            or metrics.get("realized_annualized_return")
            or metrics.get("CAGR")
            or 0.0
        )
    if key in {"realized_period_return", "minute_period_return"}:
        return float(metrics.get("realized_period_return") or metrics.get("MinuteRealizedPeriodReturnMean") or 0.0)
    if key in {"unfilled_entry_rate", "minute_unfilled_entry_rate"}:
        return float(
            metrics.get("unfilled_entry_rate")
            or metrics.get("MinuteUnfilledEntryRateMean")
            or metrics.get("MinuteUnfilledEntryMean")
            or 0.0
        )
    if key in {"forced_exit_rate", "minute_forced_exit_rate"}:
        return float(
            metrics.get("forced_exit_rate")
            or metrics.get("MinuteForcedExitRateMean")
            or metrics.get("MinuteForcedExitMean")
            or 0.0
        )
    if key in {"idle_ratio", "minute_idle_ratio"}:
        return float(metrics.get("MinuteIdleRatioMean") or 0.0)
    if key in {"active_ratio", "minute_active_ratio"}:
        return float(metrics.get("MinuteActiveRatioMean") or 0.0)
    if key in {"portfolio_excessann", "portfolio_excess_ann", "portfolio_excess"}:
        return float(metrics.get("PortfolioExcessAnn", metrics.get("ExcessAnn", 0.0)) or 0.0)
    if key in {"portfolio_cagr"}:
        return float(metrics.get("PortfolioCAGR", metrics.get("CAGR", 0.0)) or 0.0)
    if key in {"portfolio_maxdd", "portfolio_max_dd"}:
        return abs(float(metrics.get("PortfolioMaxDD", metrics.get("MaxDD", 0.0)) or 0.0))
    if key in {"portfolio_idle_ratio"}:
        return float(metrics.get("PortfolioIdleRatio", 0.0) or 0.0)
    if key in {"portfolio_utilization", "portfolio_utilization_mean"}:
        return float(metrics.get("PortfolioUtilizationMean", 0.0) or 0.0)
    if key in {"portfolio_forced_exit_rate"}:
        return float(metrics.get("PortfolioForcedExitRate", 0.0) or 0.0)
    if key in {"portfolio_unfilled_entry_rate"}:
        return float(metrics.get("PortfolioUnfilledEntryRate", 0.0) or 0.0)
    if key in {"portfolio_turnover"}:
        return float(metrics.get("PortfolioTurnover", metrics.get("AvgTurnover", 0.0)) or 0.0)
    if key in {"cagr"}:
        return float(metrics.get("CAGR") or 0.0)
    if key in {"ir", "information_ratio"}:
        return float(metrics.get("IR") or 0.0)
    if key in {"vol", "vol_ann", "volatility"}:
        return float(metrics.get("Vol_ann") or 0.0)
    if key in {"maxdd", "max_dd", "drawdown"}:
        return abs(float(metrics.get("MaxDD") or 0.0))
    if key in {"avgturnover", "avg_turnover", "turnover"}:
        return float(metrics.get("AvgTurnover") or 0.0)
    if key in {"winrate", "win_rate"}:
        return float(metrics.get("WinRate") or 0.0)
    if key in {"profitfactor", "profit_factor"}:
        return float(metrics.get("ProfitFactor") or 0.0)
    if key in {"avgholddays", "avg_hold_days"}:
        return float(metrics.get("AvgHoldDays") or 0.0)
    if key in {"sharealphaexits", "share_alpha_exits"}:
        return float(metrics.get("ShareAlphaExits") or 0.0)
    if key in {"r_d", "daily_return"}:
        return float(metrics.get("r_d") or 0.0)
    if key in {"b_d", "benchmark_daily"}:
        return float(metrics.get("b_d") or 0.0)
    if key in {"ex_d", "excess_daily"}:
        return float(metrics.get("ex_d") or 0.0)
    if key in {"sharpe", "sharpe_ann", "sharpe_annual"}:
        vol_ann = float(metrics.get("Vol_ann") or 0.0)
        r_d = float(metrics.get("r_d") or 0.0)
        annualization = float(metrics.get("AnnualizationDays") or 252.0)
        return (r_d * annualization) / vol_ann if vol_ann > 0 else 0.0
    return _excess_ann(metrics)


def _normalize_drawdown(value: float | None) -> float:
    if value is None:
        return 0.0
    value = float(value)
    return abs(value)


def _none_or_float(value: float | None) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    if math.isnan(numeric):
        return None
    return numeric


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
    annualization_days: float,
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

    vol_ann = _std(daily_returns) * (annualization_days**0.5)
    ir = 0.0
    if excess_returns:
        ex_std = _std(excess_returns)
        if ex_std > 0:
            ir = _mean(excess_returns) / ex_std * (annualization_days**0.5)

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
        "ExcessAnn": float(ex_d) * float(annualization_days),
        "CAGR": float(cagr),
        "Vol_ann": float(vol_ann),
        "IR": float(ir),
        "MaxDD": float(max_dd),
        "AvgTurnover": float(avg_turnover),
        "WinRate": float(win_rate),
        "ProfitFactor": float(profit_factor),
        "AvgHoldDays": float(avg_hold),
        "ShareAlphaExits": float(share_alpha_exits),
        "AnnualizationDays": float(annualization_days),
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
