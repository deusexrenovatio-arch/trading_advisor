from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from moex_carry.backtest_v2.engine import BacktestDataStore, BacktestReport, BacktestTrade, EquityPoint, build_rebalance_config
from moex_carry.config_resolver import ResolvedBacktestConfig, resolve_backtest_request
from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.domain.models import KeyRate
from moex_carry.domain.portfolio import PairSpec, PortfolioState, PositionState
from moex_carry.perf import resolve_pair_workers
from moex_carry.portfolio.minute_snapshot_adapter import MinutePairTape, build_minute_pair_tape
from moex_carry.portfolio.rebalance_controller import PortfolioRebalanceController, pair_key
from moex_carry.signal_replay import build_replay_settings_from_resolved, load_pair_minute_series, run_minute_replay


@dataclass
class _OpenPosition:
    pair: PairSpec
    entry_date: date
    capital: float
    entry_spread_pct_exec: float | None
    entry_price_stock: float
    entry_price_fut: float
    direction: str = "cash_and_carry"


@dataclass
class _DailyStats:
    day: date
    idle_ratio: float
    utilization: float
    entry_signals: int
    unfilled_entries: int
    exit_signals: int
    forced_exits: int
    turnover: float


_TAPE_CACHE: "OrderedDict[str, MinutePairTape]" = OrderedDict()
_TAPE_CACHE_LOCK = threading.Lock()
_TAPE_CACHE_MAX = 512


def clear_minute_replay_tape_cache() -> None:
    with _TAPE_CACHE_LOCK:
        _TAPE_CACHE.clear()


def minute_replay_tape_cache_size() -> int:
    with _TAPE_CACHE_LOCK:
        return len(_TAPE_CACHE)


def prewarm_minute_replay_tape_cache(
    *,
    request: BacktestRequest | Mapping[str, Any] | ResolvedBacktestConfig,
    universe: list[PairSpec],
    data_store: BacktestDataStore,
) -> dict[str, int]:
    resolved, _warnings = _resolve_config(request)
    start_date, end_date = _resolve_date_range(resolved)
    data_dir_raw = getattr(data_store, "data_dir", None)
    if data_dir_raw is None:
        raise ValueError("Minute portfolio engine prewarm requires data_store.data_dir")
    data_dir = Path(str(data_dir_raw))
    settings = build_replay_settings_from_resolved(resolved)
    key_rates = data_store.get_key_rates()
    execution_cfg = resolved.get("execution", {}) if isinstance(resolved, Mapping) else {}
    workers_raw = _as_int_or_none(execution_cfg.get("pair_workers")) if isinstance(execution_cfg, Mapping) else None
    workers = max(1, min(resolve_pair_workers(requested=workers_raw), max(len(universe), 1)))

    stats: dict[str, int] = {
        "pairs_total": int(len(universe)),
        "cache_hits": 0,
        "cache_misses": 0,
        "loaded": 0,
        "missing_series": 0,
    }
    if workers <= 1 or len(universe) <= 1:
        for pair in universe:
            tape = _load_pair_tape(
                pair=pair,
                data_dir=data_dir,
                start_date=start_date,
                end_date=end_date,
                settings=settings,
                key_rates=key_rates,
                cache_stats=stats,
            )
            if tape is None:
                stats["missing_series"] += 1
    else:
        pair_list = list(universe)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    _load_pair_tape,
                    pair=pair,
                    data_dir=data_dir,
                    start_date=start_date,
                    end_date=end_date,
                    settings=settings,
                    key_rates=key_rates,
                    cache_stats=stats,
                )
                for pair in pair_list
            ]
            for future in futures:
                tape = future.result()
                if tape is None:
                    stats["missing_series"] += 1
    return stats


def run_minute_portfolio_backtest(
    *,
    request: BacktestRequest | Mapping[str, Any] | ResolvedBacktestConfig,
    universe: list[PairSpec],
    data_store: BacktestDataStore,
    metric_start: date | None = None,
    metric_end: date | None = None,
) -> BacktestReport:
    resolved, warnings = _resolve_config(request)
    start_date, end_date = _resolve_date_range(resolved)
    calendar_days = _resolve_trading_days(data_store, start_date, end_date)

    data_dir_raw = getattr(data_store, "data_dir", None)
    if data_dir_raw is None:
        raise ValueError("Minute portfolio engine requires data_store.data_dir")
    data_dir = Path(str(data_dir_raw))

    settings = build_replay_settings_from_resolved(resolved)
    key_rates = data_store.get_key_rates()
    rebalance_config = build_rebalance_config(resolved)
    controller = PortfolioRebalanceController()
    execution_cfg = resolved.get("execution", {}) if isinstance(resolved, Mapping) else {}
    workers_raw = _as_int_or_none(execution_cfg.get("pair_workers")) if isinstance(execution_cfg, Mapping) else None
    workers = max(1, min(resolve_pair_workers(requested=workers_raw), max(len(universe), 1)))

    pair_map = {pair_key(pair.stock_secid, pair.future_secid): pair for pair in universe}
    tapes: dict[str, MinutePairTape] = {}
    if workers <= 1 or len(universe) <= 1:
        for pair in universe:
            tape = _load_pair_tape(
                pair=pair,
                data_dir=data_dir,
                start_date=start_date,
                end_date=end_date,
                settings=settings,
                key_rates=key_rates,
            )
            if tape is None:
                warnings.append(f"minute_tape_missing:{pair.stock_secid}:{pair.future_secid}")
                continue
            tapes[pair_key(pair.stock_secid, pair.future_secid)] = tape
    else:
        pair_list = list(universe)

        def _load_with_pair(pair: PairSpec) -> tuple[PairSpec, MinutePairTape | None]:
            return (
                pair,
                _load_pair_tape(
                    pair=pair,
                    data_dir=data_dir,
                    start_date=start_date,
                    end_date=end_date,
                    settings=settings,
                    key_rates=key_rates,
                ),
            )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_load_with_pair, pair) for pair in pair_list]
            for future in futures:
                pair, tape = future.result()
                if tape is None:
                    warnings.append(f"minute_tape_missing:{pair.stock_secid}:{pair.future_secid}")
                    continue
                tapes[pair_key(pair.stock_secid, pair.future_secid)] = tape
    if not tapes:
        raise ValueError("No minute tapes loaded for requested universe")

    tape_days = sorted(
        {
            day
            for tape in tapes.values()
            for day in tape.snapshots_by_day.keys()
            if start_date <= day <= end_date
        }
    )
    trading_days = tape_days if tape_days else calendar_days
    if not trading_days:
        raise ValueError("No trading days in requested range")

    metric_start = metric_start or trading_days[0]
    metric_end = metric_end or trading_days[-1]
    if metric_start > metric_end:
        raise ValueError("metric_start must be <= metric_end")

    portfolio_cfg = resolved.get("portfolio", {}) if isinstance(resolved, Mapping) else {}
    initial_equity = float(portfolio_cfg.get("account_equity") or 1_000_000.0)
    if initial_equity <= 0:
        initial_equity = 1_000_000.0
    cash = float(initial_equity)
    equity = float(initial_equity)
    equity_peak = float(initial_equity)

    open_positions: dict[str, _OpenPosition] = {}
    trades: list[BacktestTrade] = []
    curve: list[EquityPoint] = []
    daily_stats: list[_DailyStats] = []

    for day in trading_days:
        snapshots = _snapshots_for_day(tapes, day)
        desired_pairs, desired_weights = _desired_pairs_for_day(
            day=day,
            snapshots=snapshots,
            controller=controller,
            rebalance_config=rebalance_config,
            cash=cash,
            equity=equity,
            open_positions=open_positions,
        )
        filled_entry_pairs: set[str] = set()
        for pid, tape in tapes.items():
            entry_event = _first_entry_event_for_day(tape, day)
            if entry_event is not None and entry_event.event_type == "entry_filled":
                filled_entry_pairs.add(pid)
        if filled_entry_pairs:
            max_pairs_held = max(int(getattr(rebalance_config, "max_pairs_held", 0) or 0), 0)
            if max_pairs_held > 0:
                expanded_pairs = set(desired_pairs)
                for pid in sorted(filled_entry_pairs):
                    if pid in expanded_pairs:
                        continue
                    if len(expanded_pairs) >= max_pairs_held:
                        break
                    expanded_pairs.add(pid)
                desired_pairs = expanded_pairs
            else:
                desired_pairs = set(desired_pairs) | filled_entry_pairs
        for pid in filled_entry_pairs:
            desired_weights[pid] = max(float(desired_weights.get(pid, 0.0) or 0.0), 1.0)

        entry_signals = 0
        unfilled_entries = 0
        exit_signals = 0
        forced_exits = 0
        entered_capital = 0.0
        exited_capital = 0.0

        # Exit-first rule: minute exits always have priority.
        for pid, position in list(open_positions.items()):
            event = _first_exit_event_for_day(tapes.get(pid), day)
            if event is None:
                continue
            exit_signals += 1
            if event.event_type == "exit_forced":
                forced_exits += 1
            ret = event.trade_return_pct_net
            if ret is not None and abs(float(ret)) > 1e-12:
                pnl = position.capital * float(ret)
            elif event.trade_pnl_cash is not None:
                pnl = float(event.trade_pnl_cash)
            else:
                pnl = 0.0
            cash += position.capital + pnl
            exited_capital += position.capital
            trades.append(
                BacktestTrade(
                    pair_id=pid,
                    stock_secid=position.pair.stock_secid,
                    future_secid=position.pair.future_secid,
                    direction=position.direction,
                    entry_date=position.entry_date,
                    exit_date=day,
                    entry_price_stock=float(position.entry_price_stock),
                    entry_price_fut=float(position.entry_price_fut),
                    exit_price_stock=float(position.entry_price_stock),
                    exit_price_fut=float(position.entry_price_fut),
                    quantity_stock=1.0,
                    quantity_fut=1.0,
                    pnl=float(pnl),
                    hold_days=max((day - position.entry_date).days, 0),
                    exit_reason="EXIT_FORCED" if event.event_type == "exit_forced" else "EXIT_SIGNAL",
                )
            )
            del open_positions[pid]

        # Entries are allowed only when minute replay confirms fill.
        candidate_entries: list[tuple[str, _OpenPosition]] = []
        for pid in sorted(desired_pairs):
            if pid in open_positions:
                continue
            tape = tapes.get(pid)
            event = _first_entry_event_for_day(tape, day)
            if event is None:
                continue
            entry_signals += 1
            if event.event_type != "entry_filled":
                unfilled_entries += 1
                continue
            pair = pair_map.get(pid)
            if pair is None:
                continue
            snapshot = tape.snapshots_by_day.get(day) if tape else None
            candidate_entries.append(
                (
                    pid,
                    _OpenPosition(
                        pair=pair,
                        entry_date=day,
                        capital=0.0,
                        entry_spread_pct_exec=_safe_float(snapshot.spread_entry_exec_pct if snapshot else None),
                        entry_price_stock=_safe_float(snapshot.spot_mid if snapshot else None),
                        entry_price_fut=_safe_float(snapshot.future_mid if snapshot else None),
                    ),
                )
            )

        if candidate_entries:
            budget = max(cash * max(min(float(rebalance_config.target_utilization), 1.0), 0.0), 0.0)
            if budget > 0:
                weights = []
                for pid, _ in candidate_entries:
                    weight = max(float(desired_weights.get(pid, 0.0) or 0.0), 0.0)
                    if weight <= 0.0 and pid in filled_entry_pairs:
                        weight = 1.0
                    weights.append(weight)
                weight_sum = sum(weights)
                if weight_sum <= 0:
                    weights = [1.0] * len(candidate_entries)
                    weight_sum = float(len(candidate_entries))
                for idx, (pid, pos) in enumerate(candidate_entries):
                    alloc = min(budget * (weights[idx] / weight_sum), cash)
                    if alloc <= 0:
                        unfilled_entries += 1
                        continue
                    pos.capital = float(alloc)
                    cash -= alloc
                    entered_capital += alloc
                    open_positions[pid] = pos

        invested = sum(position.capital for position in open_positions.values())
        equity = float(cash + invested)
        equity_peak = max(equity_peak, equity)
        drawdown = (equity / equity_peak - 1.0) if equity_peak > 0 else 0.0
        turnover = (entered_capital + exited_capital) / equity if equity > 0 else 0.0
        utilization = invested / equity if equity > 0 else 0.0
        idle_ratio = cash / equity if equity > 0 else 1.0

        curve.append(
            EquityPoint(
                date=day,
                equity=equity,
                cash=float(cash),
                drawdown=float(drawdown),
                turnover=float(turnover),
                positions=len(open_positions),
            )
        )
        daily_stats.append(
            _DailyStats(
                day=day,
                idle_ratio=float(idle_ratio),
                utilization=float(utilization),
                entry_signals=int(entry_signals),
                unfilled_entries=int(unfilled_entries),
                exit_signals=int(exit_signals),
                forced_exits=int(forced_exits),
                turnover=float(turnover),
            )
        )

    metrics = _compute_summary(
        curve=curve,
        trades=trades,
        stats=daily_stats,
        resolved=resolved,
        key_rates=key_rates,
        metric_start=metric_start,
        metric_end=metric_end,
    )
    return BacktestReport(
        summary_metrics=metrics,
        equity_curve=curve,
        trades=trades,
        resolved_config=resolved,
        warnings=warnings,
        fill_quality_summary={
            "PortfolioUnfilledEntryRate": metrics.get("PortfolioUnfilledEntryRate"),
            "PortfolioForcedExitRate": metrics.get("PortfolioForcedExitRate"),
            "PortfolioIdleRatio": metrics.get("PortfolioIdleRatio"),
        },
        execution_model={
            "mode": "MINUTE_REPLAY",
            "portfolio_layer": "minute_portfolio_engine",
            "pair_workers": int(workers),
            "metric_window": {"start": metric_start.isoformat(), "end": metric_end.isoformat()},
        },
    )


def _load_pair_tape(
    *,
    pair: PairSpec,
    data_dir: Path,
    start_date: date,
    end_date: date,
    settings: Any,
    key_rates: list[KeyRate],
    cache_stats: dict[str, int] | None = None,
) -> MinutePairTape | None:
    loaded = load_pair_minute_series(
        data_dir=data_dir,
        stock=pair.stock_secid,
        future=pair.future_secid,
        start_date=start_date,
        end_date=end_date,
    )
    if loaded is None:
        return None

    source = str(loaded.source)
    source_mtime = Path(source).stat().st_mtime if Path(source).exists() else 0.0
    alpha = settings.spread_carry_alpha
    replay_sig = "|".join(
        [
            f"lag_days={alpha.signal_exec_lag_days}",
            f"lag_min={alpha.execution_lag_minutes}",
            f"wait_min={alpha.execution_max_wait_minutes}",
            f"tol={alpha.entry_price_tolerance_pct}",
            f"st_tol={alpha.entry_stock_tolerance_pct}",
            f"ft_tol={alpha.entry_future_tolerance_pct}",
            f"sp_tol={alpha.entry_spread_tolerance_pct}",
            f"cutoff={alpha.signal_cutoff_before_day_end_minutes}",
            f"source={source}",
            f"mtime={source_mtime}",
        ]
    )
    cache_key = f"{pair.stock_secid}|{pair.future_secid}|{start_date.isoformat()}|{end_date.isoformat()}|{replay_sig}"
    with _TAPE_CACHE_LOCK:
        cached = _TAPE_CACHE.get(cache_key)
        if cached is not None:
            _TAPE_CACHE.move_to_end(cache_key)
            if cache_stats is not None:
                cache_stats["cache_hits"] = int(cache_stats.get("cache_hits", 0)) + 1
            return cached
    if cache_stats is not None:
        with _TAPE_CACHE_LOCK:
            cache_stats["cache_misses"] = int(cache_stats.get("cache_misses", 0)) + 1

    replay = run_minute_replay(
        series_base=loaded.series_base,
        pair=pair,
        settings=settings,
        dividends=loaded.dividends,
        key_rates=key_rates,
    )
    tape = build_minute_pair_tape(replay=replay.replay, pair=pair)
    with _TAPE_CACHE_LOCK:
        _TAPE_CACHE[cache_key] = tape
        _TAPE_CACHE.move_to_end(cache_key)
        if len(_TAPE_CACHE) > _TAPE_CACHE_MAX:
            _TAPE_CACHE.popitem(last=False)
    if cache_stats is not None:
        with _TAPE_CACHE_LOCK:
            cache_stats["loaded"] = int(cache_stats.get("loaded", 0)) + 1
    return tape


def _snapshots_for_day(tapes: Mapping[str, MinutePairTape], day: date) -> list[Any]:
    snapshots = []
    for tape in tapes.values():
        snapshot = tape.snapshots_by_day.get(day)
        if snapshot is not None:
            snapshots.append(snapshot)
    return snapshots


def _desired_pairs_for_day(
    *,
    day: date,
    snapshots: list[Any],
    controller: PortfolioRebalanceController,
    rebalance_config: Any,
    cash: float,
    equity: float,
    open_positions: Mapping[str, _OpenPosition],
) -> tuple[set[str], dict[str, float]]:
    state = PortfolioState(
        as_of=datetime.combine(day, time.min),
        cash=float(cash),
        equity=float(equity),
        positions=[
            PositionState(
                pair=position.pair,
                direction=position.direction,
                quantity_stock=1.0,
                quantity_fut=1.0,
                entry_date=position.entry_date,
                entry_price_stock=position.entry_price_stock,
                entry_price_fut=position.entry_price_fut,
                entry_spread_exec_pct=position.entry_spread_pct_exec,
                metadata={},
            )
            for position in open_positions.values()
        ],
        open_orders=[],
        fills=[],
        metadata={"cooldowns": {}},
    )
    result = controller.rebalance(snapshots, state, rebalance_config)
    desired_pairs: set[str] = set()
    weights: dict[str, float] = {}
    for target in result.target_positions:
        pid = pair_key(target.pair.stock_secid, target.pair.future_secid)
        if int(target.contracts) <= 0:
            continue
        desired_pairs.add(pid)
        weights[pid] = float(target.weight or 0.0)
    for position in open_positions.values():
        desired_pairs.add(pair_key(position.pair.stock_secid, position.pair.future_secid))
    return desired_pairs, weights


def _first_entry_event_for_day(tape: MinutePairTape | None, day: date):
    if tape is None:
        return None
    events = tape.events_by_day.get(day, [])
    first_unfilled = None
    for event in events:
        if event.event_type == "entry_filled":
            return event
        if event.event_type == "entry_unfilled" and first_unfilled is None:
            first_unfilled = event
    return first_unfilled


def _first_exit_event_for_day(tape: MinutePairTape | None, day: date):
    if tape is None:
        return None
    events = tape.events_by_day.get(day, [])
    fallback = None
    for event in events:
        if event.event_type in {"exit_filled", "exit_forced"}:
            if event.trade_return_pct_net is not None or event.trade_pnl_cash is not None:
                return event
            if fallback is None:
                fallback = event
    return fallback


def _resolve_config(
    request: BacktestRequest | Mapping[str, Any] | ResolvedBacktestConfig,
) -> tuple[dict[str, Any], list[str]]:
    if isinstance(request, ResolvedBacktestConfig):
        return dict(request.resolved_config), list(request.warnings)
    if isinstance(request, BacktestRequest):
        resolved = resolve_backtest_request(request)
        return dict(resolved.resolved_config), list(resolved.warnings)
    validated = BacktestRequest.model_validate(request)
    resolved = resolve_backtest_request(validated)
    return dict(resolved.resolved_config), list(resolved.warnings)


def _resolve_date_range(resolved: Mapping[str, Any]) -> tuple[date, date]:
    test_cfg = resolved.get("test", {}) if isinstance(resolved, Mapping) else {}
    start = _to_date(test_cfg.get("start_date"))
    end = _to_date(test_cfg.get("end_date"))
    if start is None or end is None:
        raise ValueError("test.start_date and test.end_date are required for minute portfolio backtest")
    if start > end:
        raise ValueError("test.start_date must be <= test.end_date")
    return start, end


def _resolve_trading_days(data_store: BacktestDataStore, start_date: date, end_date: date) -> list[date]:
    return sorted(set(data_store.get_calendar(start_date, end_date)))


def _safe_float(value: Any) -> float:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return 0.0
    return float(num)


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def _as_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _compute_summary(
    *,
    curve: list[EquityPoint],
    trades: list[BacktestTrade],
    stats: list[_DailyStats],
    resolved: Mapping[str, Any],
    key_rates: list[KeyRate],
    metric_start: date,
    metric_end: date,
) -> dict[str, float]:
    window_curve = [point for point in curve if metric_start <= point.date <= metric_end]
    window_stats = [item for item in stats if metric_start <= item.day <= metric_end]
    if len(window_curve) < 2:
        empty = _empty_metrics()
        empty.update(
            {
                "PortfolioExcessAnn": 0.0,
                "PortfolioCAGR": 0.0,
                "PortfolioMaxDD": 0.0,
                "PortfolioIdleRatio": 1.0,
                "PortfolioUtilizationMean": 0.0,
                "PortfolioForcedExitRate": 0.0,
                "PortfolioUnfilledEntryRate": 0.0,
                "PortfolioTurnover": 0.0,
            }
        )
        return empty

    rates_cfg = resolved.get("rates", {}) if isinstance(resolved, Mapping) else {}
    use_trading_days = bool(rates_cfg.get("use_trading_days"))
    annualization_days = 252.0 if use_trading_days else 365.0

    rate_cache = _build_rate_cache([point.date for point in window_curve], key_rates)
    daily_returns: list[float] = []
    benchmark_returns: list[float] = []
    for idx in range(1, len(window_curve)):
        prev = window_curve[idx - 1].equity
        curr = window_curve[idx].equity
        daily_returns.append((curr / prev - 1.0) if prev > 0 else 0.0)
        benchmark_returns.append(_benchmark_daily_return(window_curve[idx].date, resolved, key_rates, rate_cache))
    turnover_ratios = [point.turnover for point in window_curve]

    window_trades = [
        trade
        for trade in trades
        if metric_start <= trade.entry_date <= metric_end and metric_start <= trade.exit_date <= metric_end
    ]
    metrics = _compute_metrics(
        equity_curve=window_curve,
        daily_returns=daily_returns,
        benchmark_returns=benchmark_returns,
        turnover_ratios=turnover_ratios,
        trades=window_trades,
        initial_equity=window_curve[0].equity,
        annualization_days=annualization_days,
    )
    metrics["PortfolioExcessAnn"] = float(metrics.get("ExcessAnn", 0.0))
    metrics["PortfolioCAGR"] = float(metrics.get("CAGR", 0.0))
    metrics["PortfolioMaxDD"] = float(metrics.get("MaxDD", 0.0))
    metrics["PortfolioIdleRatio"] = _mean([item.idle_ratio for item in window_stats])
    metrics["PortfolioUtilizationMean"] = _mean([item.utilization for item in window_stats])
    exit_signals = sum(int(item.exit_signals) for item in window_stats)
    forced_exits = sum(int(item.forced_exits) for item in window_stats)
    entry_signals = sum(int(item.entry_signals) for item in window_stats)
    unfilled_entries = sum(int(item.unfilled_entries) for item in window_stats)
    metrics["PortfolioForcedExitRate"] = float(forced_exits / exit_signals) if exit_signals > 0 else 0.0
    metrics["PortfolioUnfilledEntryRate"] = float(unfilled_entries / entry_signals) if entry_signals > 0 else 0.0
    metrics["PortfolioTurnover"] = _mean([item.turnover for item in window_stats])
    return metrics


def _compute_metrics(
    *,
    equity_curve: list[EquityPoint],
    daily_returns: list[float],
    benchmark_returns: list[float],
    turnover_ratios: list[float],
    trades: list[BacktestTrade],
    initial_equity: float,
    annualization_days: float,
) -> dict[str, float]:
    equity_values = [point.equity for point in equity_curve]
    years = max((equity_curve[-1].date - equity_curve[0].date).days / 365.0, 1 / 365.0)
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
        profit_factor = float(sum(wins) / abs(sum(losses)))
    elif wins and not losses:
        profit_factor = float("inf")
    avg_hold = _mean([float(trade.hold_days) for trade in trades]) if trades else 0.0
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
        "ShareAlphaExits": 0.0,
        "AnnualizationDays": float(annualization_days),
    }


def _empty_metrics() -> dict[str, float]:
    return {
        "r_d": 0.0,
        "b_d": 0.0,
        "ex_d": 0.0,
        "ExcessAnn": 0.0,
        "CAGR": 0.0,
        "Vol_ann": 0.0,
        "IR": 0.0,
        "MaxDD": 0.0,
        "AvgTurnover": 0.0,
        "WinRate": 0.0,
        "ProfitFactor": 0.0,
        "AvgHoldDays": 0.0,
        "ShareAlphaExits": 0.0,
        "AnnualizationDays": 252.0,
    }


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return float(variance**0.5)


def _max_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for value in values:
        peak = max(peak, value)
        dd = value / peak - 1.0 if peak > 0 else 0.0
        max_dd = min(max_dd, dd)
    return float(max_dd)


def _build_rate_cache(trading_days: Iterable[date], key_rates: list[KeyRate]) -> dict[date, KeyRate | None]:
    days = sorted(set(trading_days))
    if not days:
        return {}
    if not key_rates:
        return {day: None for day in days}
    sorted_rates = sorted(key_rates, key=lambda item: item.date)
    cache: dict[date, KeyRate | None] = {}
    idx = 0
    current: KeyRate | None = None
    for day in days:
        while idx < len(sorted_rates) and sorted_rates[idx].date <= day:
            current = sorted_rates[idx]
            idx += 1
        cache[day] = current
    return cache


def _benchmark_daily_return(
    day: date,
    resolved: Mapping[str, Any],
    key_rates: list[KeyRate],
    rate_cache: Mapping[date, KeyRate | None] | None,
) -> float:
    rates_cfg = resolved.get("rates", {}) if isinstance(resolved, Mapping) else {}
    day_count = str(rates_cfg.get("day_count") or "ACT/365").upper()
    base = 360.0 if day_count == "ACT/360" else 365.0
    r_cb = rates_cfg.get("r_cb_annual")
    key_rate_row = None
    if rate_cache is not None:
        key_rate_row = rate_cache.get(day)
    if key_rate_row is None:
        key_rate_row = latest_rate(key_rates, day)
    r_cb_value = float(r_cb) if r_cb is not None else float(key_rate_row.rate if key_rate_row else 0.0)
    return float(r_cb_value / base) if base > 0 else 0.0
