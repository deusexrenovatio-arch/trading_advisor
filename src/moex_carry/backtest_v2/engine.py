from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

import pandas as pd

from moex_carry.analytics.alpha import alpha_metrics
from moex_carry.analytics.spread import spread_entry_exec, spread_pct
from moex_carry.config_resolver import ResolvedBacktestConfig, resolve_backtest_request
from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.costs.engine import fee_fut_from_config, fee_stock_from_config
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.domain.models import DividendEvent, KeyRate
from moex_carry.domain.portfolio import (
    DailyInstrumentBar,
    Fill,
    Order,
    PairSpec,
    PortfolioState,
    PositionState,
    SnapshotPerPair,
)
from moex_carry.portfolio.contracts import RebalanceConfig
from moex_carry.portfolio.rebalance_controller import (
    EXIT_SL,
    EXIT_TP,
    EXIT_TRAIL,
    PortfolioRebalanceController,
    pair_key,
)
from moex_carry.perf import resolve_pair_workers
from moex_carry.signal_replay import (
    build_replay_settings_from_resolved,
    load_pair_minute_series,
    run_minute_replay,
)
from moex_carry.snapshot import build_snapshot_universe

FILL_TIME_EOD = "EOD"
FILL_TIME_NEXT_OPEN = "NEXT_OPEN"
EXECUTION_MODE_INTRADAY_MINUTE = "INTRADAY_MINUTE"
EXECUTION_MODE_DAILY_COMMON_MINUTE = "DAILY_COMMON_MINUTE"
EXECUTION_MODE_DAILY_EOD = "DAILY_EOD"
EXECUTION_MODE_DAILY_NEXT_OPEN = "DAILY_NEXT_OPEN"
SPREAD_HISTORY_DAYS_DEFAULT = 90
_RATE_CACHE_MISS = object()


@dataclass
class BacktestTrade:
    pair_id: str
    stock_secid: str
    future_secid: str
    direction: str
    entry_date: date
    exit_date: date
    entry_price_stock: float
    entry_price_fut: float
    exit_price_stock: float
    exit_price_fut: float
    quantity_stock: float
    quantity_fut: float
    pnl: float
    hold_days: int
    exit_reason: str | None = None


@dataclass
class EquityPoint:
    date: date
    equity: float
    cash: float
    drawdown: float
    turnover: float
    positions: int


@dataclass
class BacktestReport:
    summary_metrics: dict[str, float]
    equity_curve: list[EquityPoint]
    trades: list[BacktestTrade]
    resolved_config: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    fill_quality_summary: dict[str, Any] | None = None
    execution_model: dict[str, Any] | None = None


@dataclass
class _FastAlphaCache:
    day_index: dict[date, int]
    pair_index: dict[str, int]
    p_hit_tp: "np.ndarray"
    p_hit_sl: "np.ndarray"
    sigma_h: "np.ndarray"
    half_life: "np.ndarray"


@dataclass
class BacktestPrecomputed:
    trading_days: list[date]
    snapshots_by_day: dict[date, list[SnapshotPerPair]]
    stock_bars_by_day: dict[date, list[DailyInstrumentBar]]
    fut_bars_by_day: dict[date, list[DailyInstrumentBar]]
    dividends: list[DividendEvent]
    key_rates: list[KeyRate]
    events: dict[str, list[date]]
    resolved_config: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


class BacktestDataStore(Protocol):
    def get_stock_bars(self, as_of: date, secids: Iterable[str]) -> list[DailyInstrumentBar]:
        raise NotImplementedError

    def get_fut_bars(self, as_of: date, secids: Iterable[str]) -> list[DailyInstrumentBar]:
        raise NotImplementedError

    def get_dividends(self) -> list[DividendEvent]:
        raise NotImplementedError

    def get_key_rates(self) -> list[KeyRate]:
        raise NotImplementedError

    def get_events(self) -> dict[str, list[date]]:
        raise NotImplementedError

    def get_calendar(self, start_date: date, end_date: date) -> list[date]:
        raise NotImplementedError


@dataclass
class InMemoryDataStore:
    stock_bars: dict[date, list[DailyInstrumentBar]] = field(default_factory=dict)
    fut_bars: dict[date, list[DailyInstrumentBar]] = field(default_factory=dict)
    dividends: list[DividendEvent] = field(default_factory=list)
    key_rates: list[KeyRate] = field(default_factory=list)
    events: dict[str, list[date]] = field(default_factory=dict)
    calendar: list[date] | None = None

    def get_stock_bars(self, as_of: date, secids: Iterable[str]) -> list[DailyInstrumentBar]:
        return _filter_bars(self.stock_bars.get(as_of, []), secids)

    def get_fut_bars(self, as_of: date, secids: Iterable[str]) -> list[DailyInstrumentBar]:
        return _filter_bars(self.fut_bars.get(as_of, []), secids)

    def get_dividends(self) -> list[DividendEvent]:
        return list(self.dividends)

    def get_key_rates(self) -> list[KeyRate]:
        return list(self.key_rates)

    def get_events(self) -> dict[str, list[date]]:
        return dict(self.events)

    def get_calendar(self, start_date: date, end_date: date) -> list[date]:
        if self.calendar is not None:
            return [day for day in self.calendar if start_date <= day <= end_date]
        days = set(self.stock_bars.keys()) | set(self.fut_bars.keys())
        return sorted(day for day in days if start_date <= day <= end_date)


def precompute_backtest_data(
    request: BacktestRequest | Mapping[str, Any] | ResolvedBacktestConfig,
    universe: list[PairSpec],
    data_store: BacktestDataStore,
) -> BacktestPrecomputed:
    resolved, warnings = _resolve_config(request)
    start_date, end_date = _resolve_date_range(resolved, data_store)
    trading_days = _resolve_trading_days(data_store, start_date, end_date)
    if not trading_days:
        raise ValueError("No trading days in requested range")

    dividends = data_store.get_dividends()
    key_rates = data_store.get_key_rates()
    events = data_store.get_events() if hasattr(data_store, "get_events") else {}

    stock_secids = sorted({p.stock_secid for p in universe})
    fut_secids = sorted({p.future_secid for p in universe})

    snapshots_by_day: dict[date, list[SnapshotPerPair]] = {}
    stock_bars_by_day: dict[date, list[DailyInstrumentBar]] = {}
    fut_bars_by_day: dict[date, list[DailyInstrumentBar]] = {}

    for day in trading_days:
        stock_bars = data_store.get_stock_bars(day, stock_secids)
        fut_bars = data_store.get_fut_bars(day, fut_secids)
        stock_bars_by_day[day] = stock_bars
        fut_bars_by_day[day] = fut_bars
        snapshots_by_day[day] = build_snapshot_universe(
            as_of=day,
            pairs=universe,
            stock_bars=stock_bars,
            fut_bars=fut_bars,
            dividends=dividends,
            key_rates=key_rates,
            resolved_config=resolved,
            events=events,
        )

    return BacktestPrecomputed(
        trading_days=trading_days,
        snapshots_by_day=snapshots_by_day,
        stock_bars_by_day=stock_bars_by_day,
        fut_bars_by_day=fut_bars_by_day,
        dividends=dividends,
        key_rates=key_rates,
        events=events,
        resolved_config=resolved,
        warnings=warnings,
    )


def _prepare_fast_alpha_cache(
    *,
    precomputed: BacktestPrecomputed,
    universe: list[PairSpec],
    trading_days: list[date],
    resolved_config: Mapping[str, Any],
    warnings: list[str],
) -> _FastAlphaCache | None:
    try:
        import numpy as np

        from moex_carry.analytics.alpha import alpha_matrices_fast
    except Exception as exc:
        warnings.append(f"fast_alpha_unavailable:{exc.__class__.__name__}")
        return None

    pair_ids = [pair_key(p.stock_secid, p.future_secid) for p in universe]
    pair_index = {pair_id: idx for idx, pair_id in enumerate(pair_ids)}
    day_index = {day: idx for idx, day in enumerate(trading_days)}
    if not pair_ids or not trading_days:
        return None

    spread_pct = np.full((len(trading_days), len(pair_ids)), np.nan, dtype=float)
    for day_idx, day in enumerate(trading_days):
        snapshots = precomputed.snapshots_by_day.get(day, [])
        for snapshot in snapshots:
            pair_id = pair_key(snapshot.stock_secid, snapshot.future_secid)
            idx = pair_index.get(pair_id)
            if idx is None:
                continue
            if snapshot.spread_pct is not None:
                spread_pct[day_idx, idx] = float(snapshot.spread_pct)

    strategy_cfg = resolved_config.get("strategy", {}) if isinstance(resolved_config, Mapping) else {}
    horizon = int(strategy_cfg.get("H_max_days") or 20)
    tp_pct = float(strategy_cfg.get("TP_pct") or 0.0)
    sl_pct = float(strategy_cfg.get("SL_pct") or 0.0)
    history_days = int(strategy_cfg.get("spread_history_days") or SPREAD_HISTORY_DAYS_DEFAULT)
    if history_days <= 0:
        history_days = SPREAD_HISTORY_DAYS_DEFAULT

    p_hit_tp, p_hit_sl, sigma_h, half_life = alpha_matrices_fast(
        spread_pct,
        horizon=horizon,
        tp=tp_pct,
        sl=sl_pct,
        history_days=history_days,
    )
    return _FastAlphaCache(
        day_index=day_index,
        pair_index=pair_index,
        p_hit_tp=p_hit_tp,
        p_hit_sl=p_hit_sl,
        sigma_h=sigma_h,
        half_life=half_life,
    )


def run_backtest_v2(
    request: BacktestRequest | Mapping[str, Any] | ResolvedBacktestConfig,
    universe: list[PairSpec],
    data_store: BacktestDataStore,
    *,
    rebalance_config: RebalanceConfig | None = None,
    fill_time: str | None = None,
    precomputed: BacktestPrecomputed | None = None,
    initial_equity: float | None = None,
    compute_fill_quality: bool = True,
    fill_quality_summary_override: dict[str, Any] | None = None,
) -> BacktestReport:
    resolved, warnings = _resolve_config(request)
    start_date, end_date = _resolve_date_range(resolved, data_store)
    trading_days = _resolve_trading_days(data_store, start_date, end_date)
    if not trading_days:
        raise ValueError("No trading days in requested range")
    exec_cfg = resolved.get("execution", {}) if isinstance(resolved, Mapping) else {}
    execution_mode = _normalize_execution_mode(str(exec_cfg.get("mode") or EXECUTION_MODE_INTRADAY_MINUTE))
    if execution_mode == EXECUTION_MODE_DAILY_COMMON_MINUTE:
        warnings.append("execution.mode=DAILY_COMMON_MINUTE currently uses daily portfolio execution path")
    if execution_mode == EXECUTION_MODE_INTRADAY_MINUTE:
        warnings.append("INTRADAY_MINUTE applies canonical minute replay for fill quality summary")

    if initial_equity is None:
        portfolio_cfg = resolved.get("portfolio", {}) if isinstance(resolved, Mapping) else {}
        initial_equity = float(portfolio_cfg.get("account_equity") or 0.0)
        if initial_equity <= 0:
            initial_equity = 1_000_000.0

    if fill_time is None:
        default_fill_time = FILL_TIME_NEXT_OPEN if execution_mode == EXECUTION_MODE_DAILY_NEXT_OPEN else FILL_TIME_EOD
        fill_time = str(exec_cfg.get("fill_time") or default_fill_time)
    fill_time = _normalize_fill_time(fill_time)

    if rebalance_config is None:
        rebalance_config = build_rebalance_config(resolved)

    dividends = precomputed.dividends if precomputed is not None else data_store.get_dividends()
    key_rates = precomputed.key_rates if precomputed is not None else data_store.get_key_rates()
    rate_cache = _build_rate_cache(trading_days, key_rates)
    fill_quality_summary = None
    if compute_fill_quality and execution_mode == EXECUTION_MODE_INTRADAY_MINUTE:
        if fill_quality_summary_override is not None:
            fill_quality_summary = dict(fill_quality_summary_override)
        else:
            fill_quality_summary = _compute_intraday_fill_quality_summary(
                universe=universe,
                data_store=data_store,
                resolved_config=resolved,
                start_date=start_date,
                end_date=end_date,
                key_rates=key_rates,
                warnings=warnings,
            )
    events = (
        precomputed.events
        if precomputed is not None
        else (data_store.get_events() if hasattr(data_store, "get_events") else {})
    )
    dividend_by_date = _index_dividends_by_date(dividends)

    pair_map = {pair_key(p.stock_secid, p.future_secid): p for p in universe}
    stock_secids = sorted({p.stock_secid for p in universe})
    fut_secids = sorted({p.future_secid for p in universe})

    state = PortfolioState(
        as_of=datetime.combine(trading_days[0], time.min),
        cash=float(initial_equity),
        equity=float(initial_equity),
        positions=[],
        open_orders=[],
        fills=[],
        metadata={"cooldowns": {}},
    )

    controller = PortfolioRebalanceController()
    spread_history: dict[str, list[float]] = {pair_id: [] for pair_id in pair_map}
    equity_curve: list[EquityPoint] = []
    trades: list[BacktestTrade] = []
    turnover_ratios: list[float] = []
    daily_returns: list[float] = []
    benchmark_returns: list[float] = []
    equity_peak = float(initial_equity)

    use_precomputed_snapshots = False
    if precomputed is not None:
        if _precomputed_compatible(resolved, precomputed.resolved_config) and _precomputed_pairs_match(universe, precomputed):
            use_precomputed_snapshots = True
        else:
            warnings.append("precomputed_snapshot_mismatch: fallback_to_live_builder")
    fast_alpha_cache: _FastAlphaCache | None = None
    if use_precomputed_snapshots and precomputed is not None:
        fast_alpha_cache = _prepare_fast_alpha_cache(
            precomputed=precomputed,
            universe=universe,
            trading_days=trading_days,
            resolved_config=resolved,
            warnings=warnings,
        )

    for idx, day in enumerate(trading_days):
        state.as_of = datetime.combine(day, time.min)

        if fill_time == FILL_TIME_NEXT_OPEN and state.open_orders:
            if precomputed is not None and day in precomputed.stock_bars_by_day:
                stock_bars = precomputed.stock_bars_by_day[day]
            else:
                stock_bars = data_store.get_stock_bars(day, stock_secids)
            if precomputed is not None and day in precomputed.fut_bars_by_day:
                fut_bars = precomputed.fut_bars_by_day[day]
            else:
                fut_bars = data_store.get_fut_bars(day, fut_secids)
            fill_batch = _execute_orders(
                orders=state.open_orders,
                stock_bars=stock_bars,
                fut_bars=fut_bars,
                pair_map=pair_map,
                resolved_config=resolved,
                fill_date=day,
                use_open=True,
                warnings=warnings,
            )
            _apply_fills_to_portfolio(
                state=state,
                fills=fill_batch.fills,
                pair_map=pair_map,
                snapshot_map={},
                trades=trades,
                warnings=warnings,
            )
            state.open_orders = []
        if precomputed is not None and day in precomputed.stock_bars_by_day:
            stock_bars = precomputed.stock_bars_by_day[day]
        else:
            stock_bars = data_store.get_stock_bars(day, stock_secids)
        if precomputed is not None and day in precomputed.fut_bars_by_day:
            fut_bars = precomputed.fut_bars_by_day[day]
        else:
            fut_bars = data_store.get_fut_bars(day, fut_secids)
        if use_precomputed_snapshots and precomputed is not None and day in precomputed.snapshots_by_day:
            snapshots = precomputed.snapshots_by_day[day]
        else:
            snapshots = build_snapshot_universe(
                as_of=day,
                pairs=universe,
                stock_bars=stock_bars,
                fut_bars=fut_bars,
                dividends=dividends,
                key_rates=key_rates,
                resolved_config=resolved,
                events=events,
            )
        _enrich_snapshots(
            snapshots=snapshots,
            history=spread_history,
            resolved_config=resolved,
            key_rates=key_rates,
            rate_cache=rate_cache,
            fast_alpha_cache=fast_alpha_cache,
            day=day,
        )
        snapshot_map = {pair_key(s.stock_secid, s.future_secid): s for s in snapshots}

        _mark_to_market(
            state=state,
            snapshot_map=snapshot_map,
            day=day,
            resolved_config=resolved,
            key_rates=key_rates,
            rate_cache=rate_cache,
            dividend_by_date=dividend_by_date,
            warnings=warnings,
            apply_carry=True,
        )
        _update_position_tracking(state, snapshot_map, rebalance_config)

        rebalance_result = controller.rebalance(snapshots, state, rebalance_config)
        if rebalance_result.warnings:
            warnings.extend(rebalance_result.warnings)
        order_targets = {pair_key(t.pair.stock_secid, t.pair.future_secid): t for t in rebalance_result.target_positions}
        for order in rebalance_result.orders:
            pair_id = order.metadata.get("pair_id") if order.metadata else None
            if pair_id is None:
                continue
            reasons = rebalance_result.reasons.get(pair_id, [])
            target = order_targets.get(pair_id)
            meta = dict(order.metadata) if order.metadata else {}
            meta.update(
                {
                    "reasons": list(reasons),
                    "direction": target.direction if target else meta.get("direction"),
                    "rebalance_date": day.isoformat(),
                }
            )
            order.metadata = meta

        turnover_notional = 0.0
        if rebalance_result.orders:
            if fill_time == FILL_TIME_EOD:
                fill_batch = _execute_orders(
                    orders=rebalance_result.orders,
                    stock_bars=stock_bars,
                    fut_bars=fut_bars,
                    pair_map=pair_map,
                    resolved_config=resolved,
                    fill_date=day,
                    use_open=False,
                    warnings=warnings,
                )
                turnover_notional = fill_batch.turnover_notional
                _apply_fills_to_portfolio(
                    state=state,
                    fills=fill_batch.fills,
                    pair_map=pair_map,
                    snapshot_map=snapshot_map,
                    trades=trades,
                    warnings=warnings,
                )
                _mark_to_market(
                    state=state,
                    snapshot_map=snapshot_map,
                    day=day,
                    resolved_config=resolved,
                    key_rates=key_rates,
                    rate_cache=rate_cache,
                    dividend_by_date=dividend_by_date,
                    warnings=warnings,
                    apply_carry=False,
                )
            else:
                state.open_orders.extend(rebalance_result.orders)

        equity_value = float(state.equity or state.cash)
        equity_peak = max(equity_peak, equity_value)
        drawdown = equity_value / equity_peak - 1.0 if equity_peak > 0 else 0.0
        turnover_ratio = turnover_notional / equity_value if equity_value > 0 else 0.0

        if idx > 0:
            prev_equity = equity_curve[-1].equity
            daily_return = (equity_value / prev_equity - 1.0) if prev_equity > 0 else 0.0
            daily_returns.append(daily_return)
            benchmark_returns.append(_benchmark_daily_return(day, resolved, key_rates, rate_cache))
        turnover_ratios.append(turnover_ratio)

        equity_curve.append(
            EquityPoint(
                date=day,
                equity=equity_value,
                cash=float(state.cash),
                drawdown=drawdown,
                turnover=turnover_ratio,
                positions=len(state.positions),
            )
        )

        for snapshot in snapshots:
            if snapshot.events and snapshot.events.warnings:
                for warning in snapshot.events.warnings:
                    warnings.append(f"snapshot:{snapshot.stock_secid}:{snapshot.future_secid}:{warning}")

    rates_cfg = resolved.get("rates", {}) if isinstance(resolved, Mapping) else {}
    use_trading_days = bool(rates_cfg.get("use_trading_days"))
    annualization_days = 252.0 if use_trading_days else 365.0

    metrics = _compute_metrics(
        equity_curve=equity_curve,
        daily_returns=daily_returns,
        benchmark_returns=benchmark_returns,
        turnover_ratios=turnover_ratios,
        trades=trades,
        initial_equity=initial_equity,
        annualization_days=annualization_days,
    )

    return BacktestReport(
        summary_metrics=metrics,
        equity_curve=equity_curve,
        trades=trades,
        resolved_config=resolved,
        warnings=warnings,
        fill_quality_summary=fill_quality_summary,
        execution_model=_build_execution_model(resolved, execution_mode, fill_time),
    )


def build_rebalance_config(resolved_config: Mapping[str, Any]) -> RebalanceConfig:
    rebalance_cfg = resolved_config.get("rebalance", {}) if isinstance(resolved_config, Mapping) else {}
    strategy_cfg = resolved_config.get("strategy", {}) if isinstance(resolved_config, Mapping) else {}
    allocation_cfg = resolved_config.get("allocation", {}) if isinstance(resolved_config, Mapping) else {}
    portfolio_cfg = resolved_config.get("portfolio", {}) if isinstance(resolved_config, Mapping) else {}
    universe_cfg = resolved_config.get("universe", {}) if isinstance(resolved_config, Mapping) else {}

    cadence = str(rebalance_cfg.get("cadence") or "weekly").upper()
    if cadence.startswith("DAY"):
        soft_freq = "DAILY"
    elif cadence.startswith("WEEK"):
        soft_freq = "WEEKLY"
    else:
        soft_freq = "NONE"

    score_mode = "PERCENTILE"
    enter_total = None
    keep_total = None
    if strategy_cfg.get("min_total_score") is not None:
        score_mode = "ABSOLUTE"
        enter_total = float(strategy_cfg.get("min_total_score"))
        keep_total = float(strategy_cfg.get("min_total_score"))

    return RebalanceConfig(
        soft_rebalance_frequency=soft_freq,
        soft_rebalance_day_of_week=int(rebalance_cfg.get("soft_rebalance_day_of_week") or 0),
        hard_checks_frequency="DAILY",
        max_pairs_held=int(universe_cfg.get("max_pairs") or 6),
        cooldown_days=int(rebalance_cfg.get("cooldown_days") or 0),
        enter_min_DTE=int(strategy_cfg.get("min_DTE_entry") or 7),
        z_entry_threshold=(
            float(strategy_cfg.get("z_entry_threshold"))
            if strategy_cfg.get("z_entry_threshold") is not None
            else None
        ),
        min_floor_score=(
            float(strategy_cfg.get("min_floor_score"))
            if strategy_cfg.get("min_floor_score") is not None
            else None
        ),
        min_alpha_score=(
            float(strategy_cfg.get("min_alpha_score"))
            if strategy_cfg.get("min_alpha_score") is not None
            else None
        ),
        score_threshold_mode=score_mode,
        enter_total_score_min=enter_total,
        keep_total_score_min=keep_total,
        close_buffer_days=int(strategy_cfg.get("close_buffer_days") or 3),
        TP_pct=float(strategy_cfg.get("TP_pct") or 0.01),
        SL_pct=float(strategy_cfg.get("SL_pct") or 0.01),
        h_max_days=int(strategy_cfg.get("H_max_days") or 20),
        exit_on_floor_fail=True,
        allocation_method="EQUAL",
        target_utilization=1.0,
        max_weight_per_pair=None,
        alpha_overlay_weight=1.0,
        capital_base_mode=str(strategy_cfg.get("capital_base_mode") or "FULL_CASH"),
        margin_stock_pct=float(strategy_cfg.get("margin_stock_pct") or 0.0),
        margin_fut_pct=float(strategy_cfg.get("margin_fut_pct") or 0.0),
        var_margin_buffer_pct=float(strategy_cfg.get("var_margin_buffer_pct") or 0.0),
        min_contracts_per_pair=0,
        max_contracts_per_pair=portfolio_cfg.get("max_contracts_per_pair"),
        rebalance_band=float(rebalance_cfg.get("threshold_pct") or 0.0),
        turnover_limit_pct=allocation_cfg.get("max_turnover_pct"),
        default_direction="cash_and_carry",
    )


@dataclass
class _FillBatch:
    fills: list[Fill]
    turnover_notional: float


def _execute_orders(
    *,
    orders: list[Order],
    stock_bars: Iterable[DailyInstrumentBar],
    fut_bars: Iterable[DailyInstrumentBar],
    pair_map: Mapping[str, PairSpec],
    resolved_config: Mapping[str, Any],
    fill_date: date,
    use_open: bool,
    warnings: list[str],
) -> _FillBatch:
    if not orders:
        return _FillBatch(fills=[], turnover_notional=0.0)

    stock_map = {bar.secid: bar for bar in stock_bars}
    fut_map = {bar.secid: bar for bar in fut_bars}
    stock_secids = {pair.stock_secid for pair in pair_map.values()}
    fut_secids = {pair.future_secid for pair in pair_map.values()}

    fills: list[Fill] = []
    turnover_notional = 0.0
    fill_counter = 0

    for order in orders:
        instrument = order.instrument
        is_stock = instrument in stock_secids
        is_fut = instrument in fut_secids
        if not (is_stock or is_fut):
            warnings.append(f"unknown_instrument:{instrument}:{fill_date.isoformat()}")
            continue

        if is_stock:
            bar = stock_map.get(instrument)
        else:
            bar = fut_map.get(instrument)
        if bar is None:
            warnings.append(f"missing_bar:{instrument}:{fill_date.isoformat()}")
            continue

        price = _resolve_fill_price(
            bar=bar,
            is_future=is_fut,
            side=order.side,
            resolved_config=resolved_config,
            use_open=use_open,
        )
        if price is None:
            warnings.append(f"missing_price:{instrument}:{fill_date.isoformat()}")
            continue

        multiplier = 1.0
        if is_fut:
            pair = _pair_for_instrument(pair_map, instrument)
            multiplier = float(pair.multiplier) if pair and pair.multiplier else 1.0

        fee = _compute_fill_fee(
            price=price,
            quantity=order.quantity,
            is_future=is_fut,
            multiplier=multiplier,
            resolved_config=resolved_config,
        )
        fill_counter += 1
        fills.append(
            Fill(
                fill_id=f"FILL-{fill_date.strftime('%Y%m%d')}-{fill_counter:05d}",
                order_id=order.order_id,
                instrument=instrument,
                side=order.side,
                quantity=order.quantity,
                price=price,
                fee=fee,
                filled_at=datetime.combine(fill_date, time.min),
                metadata=dict(order.metadata) if order.metadata else {},
            )
        )
        turnover_notional += abs(order.quantity) * price * (multiplier if is_fut else 1.0)
    return _FillBatch(fills=fills, turnover_notional=turnover_notional)


def _apply_fills_to_portfolio(
    *,
    state: PortfolioState,
    fills: list[Fill],
    pair_map: Mapping[str, PairSpec],
    snapshot_map: Mapping[str, SnapshotPerPair],
    trades: list[BacktestTrade],
    warnings: list[str],
) -> None:
    if not fills:
        return

    grouped: dict[str, list[Fill]] = {}
    for fill in fills:
        meta = fill.metadata or {}
        pair_id = meta.get("pair_id")
        if not pair_id:
            warnings.append(f"missing_pair_id:{fill.instrument}")
            continue
        grouped.setdefault(pair_id, []).append(fill)

    position_map = {pair_key(pos.pair.stock_secid, pos.pair.future_secid): pos for pos in state.positions}
    cooldowns = state.metadata.setdefault("cooldowns", {})

    for pair_id in sorted(grouped.keys()):
        fills_for_pair = grouped[pair_id]
        pair = pair_map.get(pair_id)
        if pair is None:
            warnings.append(f"missing_pair:{pair_id}")
            continue

        pos = position_map.get(pair_id)
        fill_date = fills_for_pair[0].filled_at.date() if fills_for_pair[0].filled_at else date.today()
        direction = fills_for_pair[0].metadata.get("direction") or (pos.direction if pos else "cash_and_carry")
        reasons = fills_for_pair[0].metadata.get("reasons")
        exit_reason = reasons[0] if isinstance(reasons, list) and reasons else None

        stock_fills = [fill for fill in fills_for_pair if fill.instrument == pair.stock_secid]
        fut_fills = [fill for fill in fills_for_pair if fill.instrument == pair.future_secid]

        delta_stock = _net_delta(stock_fills)
        delta_fut = _net_delta(fut_fills)
        if delta_stock == 0 and delta_fut == 0:
            continue

        stock_price = _weighted_price(stock_fills)
        fut_price = _weighted_price(fut_fills)

        _apply_cash_movements(state, stock_fills, pair, is_future=False)
        _apply_cash_movements(state, fut_fills, pair, is_future=True)

        if pos is None:
            pos = PositionState(
                pair=pair,
                direction=direction,
                quantity_stock=0.0,
                quantity_fut=0.0,
                entry_date=None,
                entry_price_stock=None,
                entry_price_fut=None,
                mark_price_stock=None,
                mark_price_fut=None,
                unrealized_pnl=None,
                realized_pnl=0.0,
                metadata={},
            )
            state.positions.append(pos)
            position_map[pair_id] = pos

        old_qty_stock = pos.quantity_stock
        old_qty_fut = pos.quantity_fut
        new_qty_stock = old_qty_stock + delta_stock
        new_qty_fut = old_qty_fut + delta_fut

        if old_qty_stock != 0 and _sign(old_qty_stock) != _sign(new_qty_stock) and new_qty_stock != 0:
            _close_trade(
                pos=pos,
                pair_id=pair_id,
                pair=pair,
                exit_price_stock=stock_price,
                exit_price_fut=fut_price,
                fill_date=fill_date,
                exit_reason=exit_reason,
                trades=trades,
            )
            cooldowns[pair_id] = fill_date
            pos.quantity_stock = 0.0
            pos.quantity_fut = 0.0
            pos.entry_date = None
            pos.entry_price_stock = None
            pos.entry_price_fut = None
            pos.entry_spread_exec_pct = None
            pos.metadata["entry_fees"] = 0.0
            old_qty_stock = 0.0
            old_qty_fut = 0.0

        if old_qty_stock == 0 and new_qty_stock != 0:
            pos.entry_date = fill_date
            pos.entry_price_stock = stock_price
            pos.entry_price_fut = fut_price
            pos.quantity_stock = new_qty_stock
            pos.quantity_fut = new_qty_fut
            pos.direction = direction
            pos.metadata["entry_fees"] = _total_fees(fills_for_pair)
            snapshot = snapshot_map.get(pair_id)
            if snapshot is not None and stock_price is not None and fut_price is not None:
                pv_div = snapshot.pv_div or 0.0
                entry_spread = spread_entry_exec(stock_price, pv_div, fut_price)
                pos.entry_spread_exec_pct = spread_pct(entry_spread, snapshot.spot_mid)
            continue

        if old_qty_stock != 0 and new_qty_stock == 0:
            _close_trade(
                pos=pos,
                pair_id=pair_id,
                pair=pair,
                exit_price_stock=stock_price,
                exit_price_fut=fut_price,
                fill_date=fill_date,
                exit_reason=exit_reason,
                trades=trades,
                exit_fees=_total_fees(fills_for_pair),
            )
            cooldowns[pair_id] = fill_date
            state.positions = [p for p in state.positions if p is not pos]
            continue

        if old_qty_stock != 0 and new_qty_stock != 0:
            if abs(new_qty_stock) > abs(old_qty_stock):
                pos.entry_price_stock = _weighted_avg(
                    pos.entry_price_stock, old_qty_stock, stock_price, delta_stock
                )
                pos.entry_price_fut = _weighted_avg(
                    pos.entry_price_fut, old_qty_fut, fut_price, delta_fut
                )
                pos.quantity_stock = new_qty_stock
                pos.quantity_fut = new_qty_fut
                pos.metadata["entry_fees"] = float(pos.metadata.get("entry_fees", 0.0)) + _total_fees(
                    fills_for_pair
                )
            elif abs(new_qty_stock) < abs(old_qty_stock):
                closed_qty = abs(old_qty_stock) - abs(new_qty_stock)
                if closed_qty > 0:
                    exit_fee = _total_fees(fills_for_pair)
                    entry_fees_total = float(pos.metadata.get("entry_fees", 0.0))
                    entry_fee_alloc = entry_fees_total * (closed_qty / abs(old_qty_stock))
                    pos.metadata["entry_fees"] = max(entry_fees_total - entry_fee_alloc, 0.0)
                    _close_trade(
                        pos=pos,
                        pair_id=pair_id,
                        pair=pair,
                        exit_price_stock=stock_price,
                        exit_price_fut=fut_price,
                        fill_date=fill_date,
                        exit_reason=exit_reason,
                        trades=trades,
                        exit_fees=exit_fee,
                        entry_fee_override=entry_fee_alloc,
                        closed_qty_stock=closed_qty,
                    )
                pos.quantity_stock = new_qty_stock
                pos.quantity_fut = new_qty_fut


def _mark_to_market(
    *,
    state: PortfolioState,
    snapshot_map: Mapping[str, SnapshotPerPair],
    day: date,
    resolved_config: Mapping[str, Any],
    key_rates: list[KeyRate],
    rate_cache: Mapping[date, KeyRate | None] | None,
    dividend_by_date: Mapping[date, list[DividendEvent]],
    warnings: list[str],
    apply_carry: bool,
) -> None:
    equity = float(state.cash)
    rates_cfg = resolved_config.get("rates", {}) if isinstance(resolved_config, Mapping) else {}
    day_count = str(rates_cfg.get("day_count") or "ACT/365")
    base = 360.0 if day_count.upper() == "ACT/360" else 365.0
    r_fund = rates_cfg.get("r_fund_annual")
    key_rate_row = _resolve_key_rate(day, key_rates, rate_cache)
    r_cb_value = key_rate_row.rate if key_rate_row else 0.0
    r_fund_value = float(r_fund) if r_fund is not None else float(r_cb_value)

    if apply_carry and dividend_by_date:
        for event in dividend_by_date.get(day, []):
            for pos in state.positions:
                if pos.pair.stock_secid == event.secid and pos.quantity_stock != 0:
                    cash_delta = event.amount * pos.quantity_stock
                    state.cash += cash_delta

    for pos in state.positions:
        pair_id = pair_key(pos.pair.stock_secid, pos.pair.future_secid)
        snapshot = snapshot_map.get(pair_id)
        if snapshot is None:
            warnings.append(f"missing_snapshot:{pair_id}:{day.isoformat()}")
            continue
        mark_stock = snapshot.spot_mid or snapshot.spot_close or snapshot.spot_open
        mark_fut = snapshot.future_mid or snapshot.future_close or snapshot.future_open
        if mark_stock is None or mark_fut is None:
            warnings.append(f"missing_mark:{pair_id}:{day.isoformat()}")
        multiplier = float(pos.pair.multiplier) if pos.pair.multiplier else 1.0

        if apply_carry and mark_stock is not None and pos.quantity_stock != 0:
            funding_cost = mark_stock * pos.quantity_stock * r_fund_value / base
            state.cash -= funding_cost

        pos.mark_price_stock = mark_stock
        pos.mark_price_fut = mark_fut
        if mark_stock is not None and mark_fut is not None:
            pos.unrealized_pnl = (
                (mark_stock - (pos.entry_price_stock or mark_stock)) * pos.quantity_stock
                + (mark_fut - (pos.entry_price_fut or mark_fut)) * pos.quantity_fut * multiplier
            )
        position_value = 0.0
        if mark_stock is not None:
            position_value += pos.quantity_stock * mark_stock
        if mark_fut is not None:
            position_value += pos.quantity_fut * mark_fut * multiplier
        equity += position_value

    state.equity = equity


def _update_position_tracking(
    state: PortfolioState,
    snapshot_map: Mapping[str, SnapshotPerPair],
    config: RebalanceConfig,
) -> None:
    scores: dict[str, float] = {}
    for pair_id, snapshot in snapshot_map.items():
        if snapshot.scores.total_score is not None:
            scores[pair_id] = float(snapshot.scores.total_score)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ranks = {pair_id: idx + 1 for idx, (pair_id, _) in enumerate(ranked)}

    for pos in state.positions:
        pair_id = pair_key(pos.pair.stock_secid, pos.pair.future_secid)
        snapshot = snapshot_map.get(pair_id)
        if snapshot is None:
            continue

        liq_pass = snapshot.lq.liquidity_pass if snapshot.lq is not None else None
        if liq_pass is False:
            pos.liq_fail_streak += 1
        else:
            pos.liq_fail_streak = 0
        pos.metadata["liq_fail_streak"] = pos.liq_fail_streak

        if config.drop_rank_threshold is not None:
            rank = ranks.get(pair_id)
            if rank is not None and rank > config.drop_rank_threshold:
                pos.drop_rank_streak += 1
            else:
                pos.drop_rank_streak = 0
            pos.metadata["drop_rank_streak"] = pos.drop_rank_streak

        entry_spread = pos.entry_spread_exec_pct
        exit_spread = snapshot.spread_exit_exec_pct
        if entry_spread is not None and exit_spread is not None:
            delta = float(exit_spread) - float(entry_spread)
            peak = pos.trail_peak_spread_pct if pos.trail_peak_spread_pct is not None else delta
            pos.trail_peak_spread_pct = max(peak, delta)
            pos.metadata["trail_peak_spread_pct"] = pos.trail_peak_spread_pct


def _enrich_snapshots(
    *,
    snapshots: list[SnapshotPerPair],
    history: dict[str, list[float]],
    resolved_config: Mapping[str, Any],
    key_rates: list[KeyRate],
    rate_cache: Mapping[date, KeyRate | None] | None,
    fast_alpha_cache: _FastAlphaCache | None,
    day: date,
) -> None:
    strategy_cfg = resolved_config.get("strategy", {}) if isinstance(resolved_config, Mapping) else {}
    rates_cfg = resolved_config.get("rates", {}) if isinstance(resolved_config, Mapping) else {}
    w_floor = float(strategy_cfg.get("w_floor", 0.5))
    w_alpha = float(strategy_cfg.get("w_alpha", 0.5))
    w_liq = float(strategy_cfg.get("w_liq", 1.0))
    w_event = float(strategy_cfg.get("w_event", 1.0))
    k_event = float(strategy_cfg.get("k_event", 0.0))
    tp_pct = float(strategy_cfg.get("TP_pct") or 0.0)
    sl_pct = float(strategy_cfg.get("SL_pct") or 0.0)
    horizon = int(strategy_cfg.get("H_max_days") or 20)
    history_days = int(strategy_cfg.get("spread_history_days") or SPREAD_HISTORY_DAYS_DEFAULT)
    if history_days <= 0:
        history_days = SPREAD_HISTORY_DAYS_DEFAULT

    r_cb = rates_cfg.get("r_cb_annual")
    key_rate_row = _resolve_key_rate(day, key_rates, rate_cache)
    r_cb_value = float(r_cb) if r_cb is not None else float(key_rate_row.rate if key_rate_row else 0.0)

    liquidity_cfg = resolved_config.get("liquidity", {}) if isinstance(resolved_config, Mapping) else {}
    fast_day_idx = fast_alpha_cache.day_index.get(day) if fast_alpha_cache is not None else None

    for snapshot in snapshots:
        pair_id = pair_key(snapshot.stock_secid, snapshot.future_secid)
        series = history.setdefault(pair_id, [])
        if snapshot.spread_pct is not None:
            series.append(float(snapshot.spread_pct))
            if len(series) > history_days:
                del series[:-history_days]

        p_hit_tp = 0.0
        p_hit_sl = 0.0
        sigma_h = 0.0
        half_life = 0.0
        if fast_alpha_cache is not None and fast_day_idx is not None:
            pair_idx = fast_alpha_cache.pair_index.get(pair_id)
            if pair_idx is not None:
                p_hit_tp = float(fast_alpha_cache.p_hit_tp[fast_day_idx, pair_idx])
                p_hit_sl = float(fast_alpha_cache.p_hit_sl[fast_day_idx, pair_idx])
                sigma_h = float(fast_alpha_cache.sigma_h[fast_day_idx, pair_idx])
                half_life = float(fast_alpha_cache.half_life[fast_day_idx, pair_idx])
            else:
                alpha_stats = alpha_metrics(series, horizon=horizon, tp=tp_pct, sl=sl_pct)
                p_hit_tp = alpha_stats.p_hit_tp
                p_hit_sl = alpha_stats.p_hit_sl
                sigma_h = alpha_stats.sigma_h
                half_life = alpha_stats.half_life
        else:
            alpha_stats = alpha_metrics(series, horizon=horizon, tp=tp_pct, sl=sl_pct)
            p_hit_tp = alpha_stats.p_hit_tp
            p_hit_sl = alpha_stats.p_hit_sl
            sigma_h = alpha_stats.sigma_h
            half_life = alpha_stats.half_life

        snapshot.alpha.sigma_h = sigma_h
        snapshot.alpha.p_hit_tp = p_hit_tp
        snapshot.alpha.p_hit_sl = p_hit_sl
        snapshot.alpha.half_life = half_life

        floor_rate = snapshot.floor_rate_annual if snapshot.floor_rate_annual is not None else 0.0
        score_floor = float(floor_rate) - r_cb_value
        tp_net = tp_pct
        if snapshot.rtc_pct is not None:
            tp_net += float(snapshot.rtc_pct)
        score_alpha = p_hit_tp * tp_net - p_hit_sl * sl_pct
        if snapshot.rtc_pct is not None:
            score_alpha -= float(snapshot.rtc_pct)

        penalty_liq = 0.0
        spread_stock = snapshot.lq.spread_bps_stock if snapshot.lq is not None else None
        spread_fut = snapshot.lq.spread_bps_fut if snapshot.lq is not None else None
        max_spread_stock = liquidity_cfg.get("max_spread_bps_stock")
        max_spread_fut = liquidity_cfg.get("max_spread_bps_fut")
        if max_spread_stock is not None and spread_stock is not None:
            penalty_liq += max(0.0, float(spread_stock) - float(max_spread_stock))
        if max_spread_fut is not None and spread_fut is not None:
            penalty_liq += max(0.0, float(spread_fut) - float(max_spread_fut))
        if max_spread_stock is None and max_spread_fut is None:
            if snapshot.lq.liquidity_pass is False:
                penalty_liq += 1.0

        penalty_event = 0.0
        if snapshot.events and snapshot.events.warnings:
            lowered = {warning.lower() for warning in snapshot.events.warnings}
            if "event_blocked" in lowered or "news_blocked" in lowered:
                penalty_event = k_event

        total_score = w_floor * score_floor + w_alpha * score_alpha - w_liq * penalty_liq - w_event * penalty_event

        snapshot.scores.score_floor = score_floor
        snapshot.scores.score_alpha = score_alpha
        snapshot.scores.total_score = total_score
        snapshot.scores.penalty_liq = penalty_liq
        snapshot.scores.penalty_event = penalty_event


def _resolve_config(
    request: BacktestRequest | Mapping[str, Any] | ResolvedBacktestConfig,
) -> tuple[dict[str, Any], list[str]]:
    if isinstance(request, ResolvedBacktestConfig):
        return request.resolved_config, list(request.warnings)
    if isinstance(request, BacktestRequest):
        resolved = resolve_backtest_request(request)
        return resolved.resolved_config, list(resolved.warnings)
    if isinstance(request, Mapping):
        return dict(request), []
    raise TypeError("Unsupported backtest request type")


def _resolve_date_range(
    resolved: Mapping[str, Any],
    data_store: BacktestDataStore,
) -> tuple[date, date]:
    test_cfg = resolved.get("test", {}) if isinstance(resolved, Mapping) else {}
    start_date = test_cfg.get("start_date")
    end_date = test_cfg.get("end_date")
    if start_date is not None and end_date is not None:
        return start_date, end_date
    calendar = data_store.get_calendar(date.min, date.max)
    if not calendar:
        raise ValueError("Unable to resolve backtest date range")
    if start_date is None:
        start_date = calendar[0]
    if end_date is None:
        end_date = calendar[-1]
    return start_date, end_date


def _resolve_trading_days(
    data_store: BacktestDataStore,
    start_date: date,
    end_date: date,
) -> list[date]:
    try:
        days = data_store.get_calendar(start_date, end_date)
        if days:
            return days
    except Exception:
        pass
    return _weekday_calendar(start_date, end_date)


def _weekday_calendar(start_date: date, end_date: date) -> list[date]:
    current = start_date
    days: list[date] = []
    while current <= end_date:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


_PRECOMPUTE_CONFIG_FIELDS: dict[str, tuple[str, ...]] = {
    "execution": (
        "mode",
        "price_source",
        "common_minute_anchor",
        "price_mode",
        "half_spread_bps",
        "slip_stock_bps",
        "slip_fut_bps",
        "slip_fut_ticks",
        "tick_size_fut",
    ),
    "rates": ("day_count", "use_trading_days", "r_cb_annual", "r_fund_annual", "r_disc_annual"),
    "costs": (
        "stock_commission_bps",
        "futures_commission_bps",
        "exchange_fee_bps",
        "fee_stock_per_share",
        "fee_stock_bps",
        "fee_fut_per_contract",
    ),
    "liquidity": (
        "max_spread_bps_stock",
        "max_spread_bps_fut",
        "min_avg_dollarvol_stock",
        "min_avg_dollarvol_fut",
        "min_open_interest",
        "participation_rate",
        "max_days_to_exit",
    ),
    "strategy": (
        "floor_tolerance",
        "riskbuffer_floor",
        "capital_base_mode",
        "margin_stock_pct",
        "margin_fut_pct",
        "var_margin_buffer_pct",
        "signal_exec_lag_days",
        "execution_lag_minutes",
        "execution_max_wait_minutes",
        "entry_price_tolerance_pct",
        "entry_stock_tolerance_pct",
        "entry_future_tolerance_pct",
        "entry_spread_tolerance_pct",
        "signal_cutoff_before_day_end_minutes",
        "force_exit_policy",
        "force_exit_penalty_bps",
    ),
    "portfolio": (
        "account_equity",
        "max_gross_notional",
        "max_contracts_per_pair",
        "capital_allocated_per_trade",
    ),
    "universe": ("max_pairs",),
}


def _normalize_config_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        return tuple(value)
    return value


def _extract_config_subset(resolved: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    subset: dict[str, dict[str, Any]] = {}
    for section, keys in _PRECOMPUTE_CONFIG_FIELDS.items():
        block = resolved.get(section, {}) if isinstance(resolved, Mapping) else {}
        subset[section] = {key: _normalize_config_value(block.get(key)) for key in keys}
    return subset


def _precomputed_compatible(resolved: Mapping[str, Any], precomputed: Mapping[str, Any]) -> bool:
    return _extract_config_subset(resolved) == _extract_config_subset(precomputed)


def _precomputed_pairs_match(universe: Iterable[PairSpec], precomputed: BacktestPrecomputed) -> bool:
    universe_pairs = {pair_key(p.stock_secid, p.future_secid) for p in universe}
    for snapshots in precomputed.snapshots_by_day.values():
        if not snapshots:
            continue
        pre_pairs = {pair_key(s.stock_secid, s.future_secid) for s in snapshots}
        return pre_pairs == universe_pairs
    return True


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
    if rate_cache is not None:
        cached = rate_cache.get(day, _RATE_CACHE_MISS)
        if cached is not _RATE_CACHE_MISS:
            return cached
    return latest_rate(key_rates, day)


def _normalize_execution_mode(value: str) -> str:
    mode = str(value or "").strip().upper()
    if mode in {
        EXECUTION_MODE_INTRADAY_MINUTE,
        EXECUTION_MODE_DAILY_COMMON_MINUTE,
        EXECUTION_MODE_DAILY_EOD,
        EXECUTION_MODE_DAILY_NEXT_OPEN,
    }:
        return mode
    return EXECUTION_MODE_INTRADAY_MINUTE


def _build_execution_model(
    resolved_config: Mapping[str, Any],
    execution_mode: str,
    fill_time: str,
) -> dict[str, Any]:
    execution = resolved_config.get("execution", {}) if isinstance(resolved_config, Mapping) else {}
    strategy = resolved_config.get("strategy", {}) if isinstance(resolved_config, Mapping) else {}
    pair_workers = resolve_pair_workers(execution.get("pair_workers"))
    return {
        "mode": execution_mode,
        "fill_time": fill_time,
        "price_source": str(execution.get("price_source") or "common_minute_close"),
        "common_minute_anchor": str(execution.get("common_minute_anchor") or "last"),
        "pair_workers": int(pair_workers),
        "signal_exec_lag_days": int(strategy.get("signal_exec_lag_days") or 0),
        "execution_lag_minutes": int(strategy.get("execution_lag_minutes") or 0),
        "execution_max_wait_minutes": int(strategy.get("execution_max_wait_minutes") or 0),
        "signal_cutoff_before_day_end_minutes": int(strategy.get("signal_cutoff_before_day_end_minutes") or 0),
    }


def _safe_mean(values: list[float | None]) -> float | None:
    cleaned: list[float] = []
    for value in values:
        if value is None:
            continue
        numeric = float(value)
        if pd.isna(numeric):
            continue
        cleaned.append(numeric)
    if not cleaned:
        return None
    return float(sum(cleaned) / len(cleaned))


def _compute_intraday_fill_quality_summary(
    *,
    universe: list[PairSpec],
    data_store: BacktestDataStore,
    resolved_config: Mapping[str, Any],
    start_date: date,
    end_date: date,
    key_rates: list[KeyRate],
    warnings: list[str],
) -> dict[str, Any] | None:
    data_dir_value = getattr(data_store, "data_dir", None)
    if data_dir_value is None:
        warnings.append("intraday_minute_data_unavailable: data_store_has_no_data_dir")
        return None
    data_dir = Path(str(data_dir_value))
    settings = build_replay_settings_from_resolved(resolved_config)
    execution_cfg = resolved_config.get("execution", {}) if isinstance(resolved_config, Mapping) else {}
    workers = resolve_pair_workers(execution_cfg.get("pair_workers"))

    def _compute_pair_row(pair: PairSpec) -> dict[str, Any]:
        loaded = load_pair_minute_series(
            data_dir=data_dir,
            stock=pair.stock_secid,
            future=pair.future_secid,
            start_date=start_date,
            end_date=end_date,
        )
        if loaded is None:
            return {
                "stock": pair.stock_secid,
                "future": pair.future_secid,
                "error": "minute_series_not_found",
            }
        try:
            replay_result = run_minute_replay(
                series_base=loaded.series_base,
                pair=pair,
                settings=settings,
                dividends=loaded.dividends,
                key_rates=key_rates,
            )
            row = replay_result.metrics.to_dict()
            row.update(
                {
                    "stock": pair.stock_secid,
                    "future": pair.future_secid,
                    "source": loaded.source,
                    "cutoff_minutes": replay_result.cutoff_minutes,
                }
            )
            return row
        except Exception as exc:
            return {
                "stock": pair.stock_secid,
                "future": pair.future_secid,
                "error": f"minute_replay_failed:{exc.__class__.__name__}",
            }

    if workers <= 1:
        pair_rows = [_compute_pair_row(pair) for pair in universe]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pair_rows = list(pool.map(_compute_pair_row, universe))

    if not pair_rows:
        warnings.append("intraday_minute_data_unavailable: no_pairs")
        return None

    frame = pd.DataFrame(pair_rows)
    if frame.empty:
        warnings.append("intraday_minute_data_unavailable: empty_result")
        return None
    valid = frame[frame.get("error").isna()] if "error" in frame.columns else frame
    pairs_ok = int(len(valid))
    pairs_total = int(len(frame))
    pairs_failed = int(pairs_total - pairs_ok)

    if pairs_ok == 0:
        warnings.append("intraday_minute_data_unavailable: no_valid_pairs")
        return {
            "pair_workers": int(workers),
            "pairs_total": pairs_total,
            "pairs_ok": 0,
            "pairs_failed": pairs_failed,
            "rows": pair_rows,
        }

    def _col_values(name: str) -> list[float | None]:
        if name not in valid.columns:
            return []
        return pd.to_numeric(valid[name], errors="coerce").tolist()

    trades_closed_series = (
        pd.to_numeric(valid["trades_closed"], errors="coerce")
        if "trades_closed" in valid.columns
        else pd.Series(dtype=float)
    )

    summary = {
        "pair_workers": int(workers),
        "pairs_total": pairs_total,
        "pairs_ok": pairs_ok,
        "pairs_failed": pairs_failed,
        "avg_oper_mean": _safe_mean(_col_values("avg_trade_return_annual_operational_last5")),
        "avg_fill_to_fill_mean": _safe_mean(_col_values("avg_trade_return_annual_fill_to_fill_last5")),
        "share_target_pass_mean": _safe_mean(_col_values("share_target_pass")),
        "unfilled_entry_rate_mean": _safe_mean(_col_values("unfilled_entry_rate")),
        "unfilled_exit_rate_mean": _safe_mean(_col_values("unfilled_exit_rate")),
        "forced_exit_rate_mean": _safe_mean(_col_values("forced_exit_rate")),
        "avg_entry_wait_min_closed_mean": _safe_mean(_col_values("avg_entry_wait_min_closed")),
        "avg_exit_wait_min_closed_mean": _safe_mean(_col_values("avg_exit_wait_min_closed")),
        "trades_closed_total": int(trades_closed_series.fillna(0.0).sum()),
        "rows": pair_rows,
    }
    return summary


def _normalize_fill_time(value: str) -> str:
    upper = value.strip().upper()
    if upper in {FILL_TIME_EOD, FILL_TIME_NEXT_OPEN}:
        return upper
    return FILL_TIME_EOD


def _index_dividends_by_date(dividends: Iterable[DividendEvent]) -> dict[date, list[DividendEvent]]:
    grouped: dict[date, list[DividendEvent]] = {}
    for event in dividends:
        grouped.setdefault(event.ex_date, []).append(event)
    return grouped


def _filter_bars(bars: Iterable[DailyInstrumentBar], secids: Iterable[str]) -> list[DailyInstrumentBar]:
    target = set(secids)
    return [bar for bar in bars if bar.secid in target]


def _pair_for_instrument(pair_map: Mapping[str, PairSpec], instrument: str) -> PairSpec | None:
    for pair in pair_map.values():
        if pair.stock_secid == instrument or pair.future_secid == instrument:
            return pair
    return None


def _resolve_fill_price(
    *,
    bar: DailyInstrumentBar,
    is_future: bool,
    side: str,
    resolved_config: Mapping[str, Any],
    use_open: bool,
) -> float | None:
    exec_cfg = resolved_config.get("execution", {}) if isinstance(resolved_config, Mapping) else {}
    base_price = bar.open if use_open else bar.close
    if base_price is None:
        base_price = bar.mid or bar.last or bar.bid or bar.ask
    if base_price is None:
        return None

    half_spread_bps = float(exec_cfg.get("half_spread_bps") or 0.0)
    bid = bar.bid
    ask = bar.ask
    if bid is None or ask is None:
        spread = half_spread_bps / 10000.0
        bid = float(base_price) * (1.0 - spread)
        ask = float(base_price) * (1.0 + spread)

    price = float(ask) if side == "buy" else float(bid)
    slip_stock_bps = float(exec_cfg.get("slip_stock_bps") or 0.0)
    slip_fut_bps = float(exec_cfg.get("slip_fut_bps") or 0.0)
    slip_fut_ticks = exec_cfg.get("slip_fut_ticks")
    tick_size_fut = exec_cfg.get("tick_size_fut")
    if is_future:
        return _apply_fut_slip(price, side, slip_fut_bps, slip_fut_ticks, tick_size_fut)
    return _apply_bps(price, slip_stock_bps, side)


def _compute_fill_fee(
    *,
    price: float,
    quantity: float,
    is_future: bool,
    multiplier: float,
    resolved_config: Mapping[str, Any],
) -> float:
    costs_cfg = resolved_config.get("costs", {}) if isinstance(resolved_config, Mapping) else {}
    if is_future:
        fee_per_share = fee_fut_from_config(multiplier, costs_cfg)
        return float(fee_per_share) * float(quantity)
    fee_per_share = fee_stock_from_config(price, costs_cfg)
    return float(fee_per_share) * float(quantity)


def _net_delta(fills: list[Fill]) -> float:
    total = 0.0
    for fill in fills:
        sign = 1.0 if fill.side == "buy" else -1.0
        total += sign * float(fill.quantity)
    return total


def _weighted_price(fills: list[Fill]) -> float | None:
    if not fills:
        return None
    total_qty = 0.0
    total_val = 0.0
    for fill in fills:
        qty = float(fill.quantity)
        total_qty += qty
        total_val += qty * float(fill.price)
    return total_val / total_qty if total_qty else None


def _total_fees(fills: list[Fill]) -> float:
    return float(sum(float(fill.fee or 0.0) for fill in fills))


def _apply_cash_movements(
    state: PortfolioState, fills: list[Fill], pair: PairSpec, *, is_future: bool
) -> None:
    multiplier = float(pair.multiplier) if pair.multiplier else 1.0
    for fill in fills:
        sign = -1.0 if fill.side == "buy" else 1.0
        notional = float(fill.quantity) * float(fill.price)
        if is_future:
            notional *= multiplier
        fee = float(fill.fee or 0.0)
        state.cash += sign * notional - fee


def _apply_bps(price: float, bps: float, side: str) -> float:
    if bps == 0.0:
        return price
    adj = bps / 10000.0
    return price * (1.0 + adj) if side == "buy" else price * (1.0 - adj)


def _apply_fut_slip(
    price: float,
    side: str,
    slip_fut_bps: float,
    slip_fut_ticks: float | None,
    tick_size_fut: float | None,
) -> float:
    if slip_fut_ticks is not None and tick_size_fut is not None:
        delta = float(slip_fut_ticks) * float(tick_size_fut)
        return price + delta if side == "buy" else price - delta
    return _apply_bps(price, slip_fut_bps, side)


def _close_trade(
    *,
    pos: PositionState,
    pair_id: str,
    pair: PairSpec,
    exit_price_stock: float | None,
    exit_price_fut: float | None,
    fill_date: date,
    exit_reason: str | None,
    trades: list[BacktestTrade],
    exit_fees: float | None = None,
    entry_fee_override: float | None = None,
    closed_qty_stock: float | None = None,
) -> None:
    if pos.entry_date is None or pos.entry_price_stock is None or pos.entry_price_fut is None:
        return
    if exit_price_stock is None or exit_price_fut is None:
        return

    multiplier = float(pair.multiplier) if pair.multiplier else 1.0
    stock_sign = _sign(pos.quantity_stock)
    stock_qty_signed = pos.quantity_stock
    if closed_qty_stock is not None:
        stock_qty_signed = closed_qty_stock * stock_sign

    fut_qty_signed = pos.quantity_fut
    if closed_qty_stock is not None and abs(pos.quantity_stock) > 0:
        scale = closed_qty_stock / abs(pos.quantity_stock)
        fut_qty_signed = pos.quantity_fut * scale

    qty_stock = abs(stock_qty_signed)
    qty_fut = abs(fut_qty_signed)

    pnl = (exit_price_stock - pos.entry_price_stock) * stock_qty_signed
    pnl += (exit_price_fut - pos.entry_price_fut) * fut_qty_signed * multiplier

    entry_fees = entry_fee_override if entry_fee_override is not None else float(pos.metadata.get("entry_fees", 0.0))
    pnl -= float(entry_fees)
    if exit_fees is not None:
        pnl -= float(exit_fees)

    hold_days = (fill_date - pos.entry_date).days
    trades.append(
        BacktestTrade(
            pair_id=pair_id,
            stock_secid=pair.stock_secid,
            future_secid=pair.future_secid,
            direction=pos.direction,
            entry_date=pos.entry_date,
            exit_date=fill_date,
            entry_price_stock=pos.entry_price_stock,
            entry_price_fut=pos.entry_price_fut,
            exit_price_stock=exit_price_stock,
            exit_price_fut=exit_price_fut,
            quantity_stock=qty_stock,
            quantity_fut=qty_fut,
            pnl=pnl,
            hold_days=hold_days,
            exit_reason=exit_reason,
        )
    )


def _weighted_avg(old_price: float | None, old_qty: float, new_price: float | None, delta_qty: float) -> float | None:
    if old_price is None or new_price is None:
        return old_price or new_price
    total_qty = abs(old_qty) + abs(delta_qty)
    if total_qty == 0:
        return old_price
    return (old_price * abs(old_qty) + new_price * abs(delta_qty)) / total_qty


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


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
    alpha_exit_reasons = {EXIT_TP, EXIT_SL, EXIT_TRAIL}
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
