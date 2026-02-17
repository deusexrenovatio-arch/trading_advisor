from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from moex_carry.backtest_v2.runtime import build_universe_from_request
from moex_carry.config_resolver import resolve_backtest_request
from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.domain.models import KeyRate
from moex_carry.perf import resolve_pair_workers
from moex_carry.signal_replay import build_replay_settings_from_resolved, load_pair_minute_series, run_minute_replay


@dataclass(frozen=True)
class PairWindowMetrics:
    stock: str
    future: str
    metrics: dict[str, Any]


def compute_minute_window_metrics(
    *,
    request: BacktestRequest,
    start_date: date,
    end_date: date,
    data_dir: Path,
) -> dict[str, float]:
    if start_date > end_date:
        return _invalid_window_metrics()

    resolved = resolve_backtest_request(request)
    settings = build_replay_settings_from_resolved(resolved.resolved_config)
    key_rates = _load_key_rates(Path(data_dir))
    universe = build_universe_from_request(request, Path(data_dir))
    fail_fast = bool(getattr(request.execution, "minute_fail_fast", True))
    workers_raw = getattr(request.execution, "pair_workers", None)
    workers = max(1, min(resolve_pair_workers(requested=workers_raw), max(len(universe), 1)))

    pair_rows: list[PairWindowMetrics] = []
    missing_pairs: list[str] = []

    def _evaluate_pair(pair: Any) -> tuple[PairWindowMetrics | None, str | None]:
        loaded = load_pair_minute_series(
            data_dir=Path(data_dir),
            stock=pair.stock_secid,
            future=pair.future_secid,
            start_date=start_date,
            end_date=end_date,
        )
        if loaded is None:
            pair_id_value = f"{pair.stock_secid}:{pair.future_secid}"
            if fail_fast:
                return None, pair_id_value
            return (
                PairWindowMetrics(
                    stock=pair.stock_secid,
                    future=pair.future_secid,
                    metrics={"error": "minute_series_not_found"},
                ),
                None,
            )
        try:
            replay_result = run_minute_replay(
                series_base=loaded.series_base,
                pair=pair,
                settings=settings,
                dividends=loaded.dividends,
                key_rates=key_rates,
            )
            metrics = _period_pnl_metrics(replay=replay_result.replay, settings=settings, key_rates=key_rates)
        except Exception as exc:
            metrics = {"error": f"minute_replay_failed:{exc.__class__.__name__}"}
        return PairWindowMetrics(stock=pair.stock_secid, future=pair.future_secid, metrics=metrics), None

    if workers <= 1 or len(universe) <= 1:
        for pair in universe:
            row, missing = _evaluate_pair(pair)
            if missing is not None:
                missing_pairs.append(missing)
                continue
            if row is not None:
                pair_rows.append(row)
    else:
        pair_list = list(universe)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_evaluate_pair, pair) for pair in pair_list]
            for future in futures:
                row, missing = future.result()
                if missing is not None:
                    missing_pairs.append(missing)
                    continue
                if row is not None:
                    pair_rows.append(row)

    if missing_pairs and fail_fast:
        sample = ",".join(missing_pairs[:20])
        raise ValueError(f"minute_fail_fast_missing_series:{sample}")
    return _aggregate_pair_metrics(pair_rows)


def evaluate_minute_period_metrics(
    *,
    request: BacktestRequest,
    data_dir: Path,
    start_date: date,
    end_date: date,
) -> dict[str, float]:
    """Backward-compatible alias used by existing tests and scripts."""
    return compute_minute_window_metrics(
        request=request,
        start_date=start_date,
        end_date=end_date,
        data_dir=data_dir,
    )


def _load_key_rates(data_dir: Path) -> list[KeyRate]:
    path = data_dir / "raw" / "key_rates.csv"
    if not path.exists():
        return []
    frame = pd.read_csv(path)
    if frame.empty:
        return []
    rates: list[KeyRate] = []
    for row in frame.to_dict("records"):
        day_raw = row.get("date")
        rate_raw = row.get("rate")
        day = pd.to_datetime(day_raw, errors="coerce").date() if day_raw else None
        rate = _safe_float(rate_raw)
        if day and rate is not None:
            rates.append(KeyRate(date=day, rate=rate))
    return rates


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _safe_mean(values: Iterable[float | None]) -> float | None:
    cleaned: list[float] = []
    for value in values:
        if value is None:
            continue
        numeric = float(value)
        if not math.isfinite(numeric):
            continue
        cleaned.append(numeric)
    if not cleaned:
        return None
    return float(sum(cleaned) / len(cleaned))


def _safe_median(values: Iterable[float | None]) -> float | None:
    cleaned: list[float] = []
    for value in values:
        if value is None:
            continue
        numeric = float(value)
        if not math.isfinite(numeric):
            continue
        cleaned.append(numeric)
    if not cleaned:
        return None
    return float(pd.Series(cleaned, dtype="float64").median())


def _day_count_basis(day_count: str) -> float:
    raw = str(day_count or "ACT/365").upper()
    return 360.0 if "360" in raw else 365.0


def _target_annual_rate(
    *,
    settings: Any,
    key_rates: list[KeyRate],
    period_start: date,
    period_end: date,
) -> float:
    alpha = settings.spread_carry_alpha
    if alpha.annual_target_threshold is not None:
        return float(alpha.annual_target_threshold)
    if alpha.r_cb_annual is not None:
        return float(alpha.r_cb_annual)
    days = pd.date_range(period_start, period_end, freq="D")
    rates: list[float] = []
    for ts in days:
        point = latest_rate(key_rates, ts.date())
        if point is not None and point.rate is not None:
            rates.append(float(point.rate))
    if not rates:
        return 0.0
    return float(pd.Series(rates, dtype="float64").mean())


def _safe_annualize(growth_factor: float, period_days: int, year_basis: float) -> float | None:
    if period_days <= 0:
        return None
    if growth_factor <= 0.0:
        return None
    return float(math.pow(growth_factor, year_basis / float(period_days)) - 1.0)


def _execution_quality_stats(series_df: pd.DataFrame) -> dict[str, float | None]:
    if series_df.empty:
        return {
            "share_target_pass": None,
            "unfilled_entry_rate": None,
            "unfilled_exit_rate": None,
            "forced_exit_rate": None,
        }

    action_series = (
        series_df["signal_action"].astype(str).str.lower()
        if "signal_action" in series_df.columns
        else pd.Series([], dtype="string")
    )
    entry_signal_mask = action_series == "enter"
    exit_signal_mask = action_series == "exit"
    entry_signals = int(entry_signal_mask.sum())
    exit_signals = int(exit_signal_mask.sum())

    entry_status = (
        series_df["entry_fill_status"]
        if "entry_fill_status" in series_df.columns
        else pd.Series(index=series_df.index, dtype="object")
    )
    exit_status = (
        series_df["exit_fill_status"]
        if "exit_fill_status" in series_df.columns
        else pd.Series(index=series_df.index, dtype="object")
    )

    entry_unfilled = int((entry_status[entry_signal_mask] == "entry_unfilled").sum())
    exit_unfilled = int((exit_status[exit_signal_mask] == "exit_unfilled").sum())
    forced_exits = int((exit_status[exit_signal_mask] == "forced").sum())

    exit_mask = (
        series_df["exit_flag"].fillna(False).astype(bool)
        if "exit_flag" in series_df.columns
        else pd.Series(False, index=series_df.index)
    )
    annual_pass = series_df.get("annual_target_pass")
    if annual_pass is None:
        share_target_pass = None
    else:
        pass_values = annual_pass[exit_mask & annual_pass.notna()]
        share_target_pass = float(pass_values.astype(float).mean()) if not pass_values.empty else None

    return {
        "share_target_pass": share_target_pass,
        "unfilled_entry_rate": float(entry_unfilled / entry_signals) if entry_signals > 0 else None,
        "unfilled_exit_rate": float(exit_unfilled / exit_signals) if exit_signals > 0 else None,
        "forced_exit_rate": float(forced_exits / exit_signals) if exit_signals > 0 else None,
    }


def _period_pnl_metrics(
    *,
    replay: pd.DataFrame,
    settings: Any,
    key_rates: list[KeyRate],
) -> dict[str, Any]:
    if replay.empty:
        return {"error": "replay_empty"}

    work = replay.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.date
    work = work.dropna(subset=["date"])
    if work.empty:
        return {"error": "replay_dates_empty"}

    period_start = min(work["date"])
    period_end = max(work["date"])
    period_days = max((period_end - period_start).days, 1)
    year_basis = float(_day_count_basis(settings.spread_carry_alpha.day_count))

    action = (
        work["signal_action"].astype(str).str.lower()
        if "signal_action" in work.columns
        else pd.Series(dtype="string")
    )
    entry_signals = int((action == "enter").sum())
    exit_signals = int((action == "exit").sum())

    exit_mask = (
        work["exit_flag"].fillna(False).astype(bool)
        if "exit_flag" in work.columns
        else pd.Series(False, index=work.index)
    )
    closed = work.loc[exit_mask].copy()

    trade_returns = pd.to_numeric(closed.get("trade_return_pct_net"), errors="coerce").dropna()
    trade_pnls = pd.to_numeric(closed.get("trade_pnl_cash"), errors="coerce").dropna()
    trade_holds = pd.to_numeric(closed.get("trade_hold_days"), errors="coerce").dropna()

    growth_factor = 1.0
    for value in trade_returns.tolist():
        growth_factor *= 1.0 + float(value)
    period_return = float(growth_factor - 1.0)
    annualized_realized = _safe_annualize(growth_factor, period_days, year_basis)

    target_annual = _target_annual_rate(
        settings=settings,
        key_rates=key_rates,
        period_start=period_start,
        period_end=period_end,
    )
    target_growth = math.pow(1.0 + target_annual, float(period_days) / year_basis)
    target_period_return = float(target_growth - 1.0)

    active_days = float(trade_holds.clip(lower=0).sum()) if not trade_holds.empty else 0.0
    active_ratio = float(min(max(active_days / float(period_days), 0.0), 1.0))
    idle_ratio = float(1.0 - active_ratio)

    execution_stats = _execution_quality_stats(work)
    open_position_end = False
    if "entry_fill_status" in work.columns and "exit_fill_status" in work.columns:
        pending_entry = work["entry_fill_status"].astype(str).str.lower().eq("filled").sum()
        pending_exit = work["exit_fill_status"].astype(str).str.lower().isin({"filled", "forced"}).sum()
        open_position_end = int(pending_entry) > int(pending_exit)

    excess_annual = float(annualized_realized - target_annual) if annualized_realized is not None else None
    annual_target_pass = bool(annualized_realized >= target_annual) if annualized_realized is not None else None
    period_target_pass = bool(period_return >= target_period_return)

    return {
        "error": None,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "period_days": int(period_days),
        "entry_signals": entry_signals,
        "exit_signals": exit_signals,
        "trades_closed": int(len(trade_returns)),
        "realized_pnl_cash_sum": float(trade_pnls.sum()) if not trade_pnls.empty else 0.0,
        "realized_growth_factor": float(growth_factor),
        "realized_period_return": period_return,
        "realized_annualized_return": annualized_realized,
        "target_annual_rate": float(target_annual),
        "target_period_return": target_period_return,
        "excess_annual_vs_target": excess_annual,
        "annual_target_pass": annual_target_pass,
        "period_target_pass": period_target_pass,
        "active_days_sum": active_days,
        "active_ratio": active_ratio,
        "idle_ratio": idle_ratio,
        "share_target_pass_exit_rows": execution_stats.get("share_target_pass"),
        "unfilled_entry_rate": execution_stats.get("unfilled_entry_rate"),
        "forced_exit_rate": execution_stats.get("forced_exit_rate"),
        "open_position_end": open_position_end,
    }


def _invalid_window_metrics() -> dict[str, float]:
    return {
        "CAGR": float("nan"),
        "ExcessAnn": float("nan"),
        "MaxDD": 0.0,
        "AvgTurnover": 0.0,
        "Vol_ann": 0.0,
        "IR": 0.0,
        "r_d": 0.0,
        "b_d": 0.0,
        "ex_d": 0.0,
        "MinutePairsTotal": 0.0,
        "MinutePairsOk": 0.0,
        "MinutePairs": 0.0,
        "MinutePairsFailed": 0.0,
        "MinuteTradesClosedTotal": 0.0,
        "MinuteUnfilledEntryMean": float("nan"),
        "MinuteForcedExitMean": float("nan"),
    }


def _aggregate_pair_metrics(rows: list[PairWindowMetrics]) -> dict[str, float]:
    if not rows:
        return _invalid_window_metrics()

    valid_rows = [row.metrics for row in rows if not row.metrics.get("error")]
    if not valid_rows:
        return _invalid_window_metrics() | {
            "MinutePairsTotal": float(len(rows)),
            "MinutePairsOk": 0.0,
            "MinutePairsFailed": float(len(rows)),
        }

    realized_annual = [_safe_float(item.get("realized_annualized_return")) for item in valid_rows]
    excess_annual = [_safe_float(item.get("excess_annual_vs_target")) for item in valid_rows]
    realized_period = [_safe_float(item.get("realized_period_return")) for item in valid_rows]
    unfilled_entry = [_safe_float(item.get("unfilled_entry_rate")) for item in valid_rows]
    forced_exit = [_safe_float(item.get("forced_exit_rate")) for item in valid_rows]
    idle_ratio = [_safe_float(item.get("idle_ratio")) for item in valid_rows]
    active_ratio = [_safe_float(item.get("active_ratio")) for item in valid_rows]
    target_pass = [
        _safe_float(item.get("annual_target_pass")) if item.get("annual_target_pass") is not None else None
        for item in valid_rows
    ]
    trades_closed_values = [_safe_float(item.get("trades_closed")) for item in valid_rows]
    trades_closed_total = int(sum(value for value in trades_closed_values if value is not None))

    cagr_mean = _safe_mean(realized_annual)
    excess_mean = _safe_mean(excess_annual)
    cagr_median = _safe_median(realized_annual)
    excess_median = _safe_median(excess_annual)
    realized_period_mean = _safe_mean(realized_period)
    unfilled_entry_mean = _safe_mean(unfilled_entry)
    forced_exit_mean = _safe_mean(forced_exit)
    idle_ratio_mean = _safe_mean(idle_ratio)
    active_ratio_mean = _safe_mean(active_ratio)
    target_pass_mean = _safe_mean(target_pass)

    metrics: dict[str, float] = {
        "CAGR": float(cagr_mean) if cagr_mean is not None else float("nan"),
        "ExcessAnn": float(excess_mean) if excess_mean is not None else float("nan"),
        "MaxDD": 0.0,
        "AvgTurnover": 0.0,
        "Vol_ann": 0.0,
        "IR": 0.0,
        "r_d": 0.0,
        "b_d": 0.0,
        "ex_d": float(excess_mean) / 365.0 if excess_mean is not None else float("nan"),
        "MinuteRealizedAnnualMean": float(cagr_mean) if cagr_mean is not None else float("nan"),
        "MinuteRealizedAnnualMedian": float(cagr_median) if cagr_median is not None else float("nan"),
        "MinuteExcessAnnMean": float(excess_mean) if excess_mean is not None else float("nan"),
        "MinuteExcessAnnMedian": float(excess_median) if excess_median is not None else float("nan"),
        "MinuteRealizedPeriodReturnMean": float(realized_period_mean) if realized_period_mean is not None else float("nan"),
        "MinuteUnfilledEntryRateMean": float(unfilled_entry_mean) if unfilled_entry_mean is not None else float("nan"),
        "MinuteForcedExitRateMean": float(forced_exit_mean) if forced_exit_mean is not None else float("nan"),
        "MinuteIdleRatioMean": float(idle_ratio_mean) if idle_ratio_mean is not None else float("nan"),
        "MinuteActiveRatioMean": float(active_ratio_mean) if active_ratio_mean is not None else float("nan"),
        "MinuteAnnualTargetPassRateMean": float(target_pass_mean) if target_pass_mean is not None else float("nan"),
        "MinuteTradesClosedTotal": float(trades_closed_total),
        "MinutePairsTotal": float(len(rows)),
        "MinutePairsOk": float(len(valid_rows)),
        "MinutePairs": float(len(valid_rows)),
        "MinutePairsFailed": float(len(rows) - len(valid_rows)),
        "realized_annualized_return": float(cagr_mean) if cagr_mean is not None else float("nan"),
        "excess_annual_vs_target": float(excess_mean) if excess_mean is not None else float("nan"),
        "realized_period_return": float(realized_period_mean) if realized_period_mean is not None else float("nan"),
        "unfilled_entry_rate": float(unfilled_entry_mean) if unfilled_entry_mean is not None else float("nan"),
        "forced_exit_rate": float(forced_exit_mean) if forced_exit_mean is not None else float("nan"),
        "MinuteUnfilledEntryMean": float(unfilled_entry_mean) if unfilled_entry_mean is not None else float("nan"),
        "MinuteForcedExitMean": float(forced_exit_mean) if forced_exit_mean is not None else float("nan"),
    }
    return metrics
