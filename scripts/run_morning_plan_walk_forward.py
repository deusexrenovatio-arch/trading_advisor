from __future__ import annotations

import argparse
import copy
import itertools
import json
import math
import random
import re
import sqlite3
import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from moex_carry.config import AppSettings, load_settings
from moex_carry.data.moex_iss import MoexIssClient
from moex_carry.hpo.search_space import parse_search_space, sample_random, sample_tpe
from moex_carry.signal_engine.core.calendar import MarketCalendar, parse_time_window
from moex_carry.signal_engine.core.math_utils import price_to_ticks
from moex_carry.signal_engine.core.ohlcv import resample_ohlcv
from moex_carry.signal_engine.core.types import Candle, ExecutionParams, Level, RegimeState, Setup, Side, TF
from moex_carry.signal_engine.data.candles import InMemoryCandleProvider
from moex_carry.signal_engine.execution.engine import ExecutionEngine
from moex_carry.signal_engine.levels.engine import LevelEngine
from moex_carry.signal_engine.regime.engine import RegimeEngine
from moex_carry.signal_engine.setups.generator import SetupGenerator
from moex_carry.signal_engine.plan.builder import MorningPlanBuilder

TUNING_GRID_PROFILES: dict[str, dict[str, list[float]]] = {
    "baseline_v1": {
        "execution.buffer_atr_mult": [0.08, 0.10, 0.12],
        "setups.rr_default": [1.4, 1.6],
        "setups.pullback_max_dist_atr_mult": [0.8, 1.0],
    },
    "cost_aware_v2": {
        "execution.buffer_atr_mult": [0.08, 0.10],
        "setups.min_rr_net": [1.0, 1.2],
        "setups.min_reward_net_ticks": [1.0, 2.0],
        "setups.max_risk_atr_mult": [1.0, 1.2],
        "setups.sl_atr_mult": [0.7, 0.8],
    },
}

TUNING_SEARCH_SPACE_PROFILES: dict[str, dict[str, Any]] = {
    "intraday_goal_v1": {
        "execution.buffer_atr_mult": {"type": "float", "min": 0.05, "max": 0.20, "step": 0.01},
        "setups.rr_default": {"type": "float", "min": 1.2, "max": 2.8, "step": 0.1},
        "setups.pullback_max_dist_atr_mult": {"type": "float", "min": 0.5, "max": 1.3, "step": 0.1},
        "setups.max_risk_atr_mult": {"type": "float", "min": 0.8, "max": 1.8, "step": 0.1},
        "setups.sl_atr_mult": {"type": "float", "min": 0.6, "max": 1.2, "step": 0.1},
        "setups.min_rr_net": {"type": "float", "min": 1.0, "max": 1.8, "step": 0.1},
        "setups.min_reward_net_ticks": {"type": "float", "min": 1.0, "max": 6.0, "step": 1.0},
        "setups.min_reward_gross_ticks": {"type": "float", "min": 8.0, "max": 40.0, "step": 2.0},
        "setups.min_target_return_pct": {"type": "float", "min": 0.5, "max": 1.5, "step": 0.1},
        "setups.min_atr_h1_cost_mult": {"type": "float", "min": 4.0, "max": 10.0, "step": 1.0},
        "setups.min_atr_d1_cost_mult": {"type": "float", "min": 8.0, "max": 20.0, "step": 2.0},
    },
    "intraday_goal_v2": {
        "execution.buffer_atr_mult": {"type": "float", "min": 0.08, "max": 0.16, "step": 0.01},
        "setups.rr_default": {"type": "float", "min": 1.4, "max": 2.2, "step": 0.1},
        "setups.pullback_max_dist_atr_mult": {"type": "float", "min": 0.6, "max": 1.0, "step": 0.1},
        "setups.max_risk_atr_mult": {"type": "float", "min": 0.9, "max": 1.3, "step": 0.1},
        "setups.sl_atr_mult": {"type": "float", "min": 0.7, "max": 0.9, "step": 0.1},
        "setups.min_rr_net": {"type": "float", "min": 1.1, "max": 1.5, "step": 0.1},
        "setups.min_reward_net_ticks": {"type": "float", "min": 2.0, "max": 4.0, "step": 1.0},
        "setups.min_reward_gross_ticks": {"type": "float", "min": 12.0, "max": 24.0, "step": 2.0},
        "setups.min_target_return_pct": {"type": "float", "min": 0.5, "max": 1.0, "step": 0.1},
        "setups.min_atr_h1_cost_mult": {"type": "float", "min": 5.0, "max": 8.0, "step": 1.0},
        "setups.min_atr_d1_cost_mult": {"type": "float", "min": 10.0, "max": 16.0, "step": 2.0},
    },
    "intraday_goal_v3": {
        "execution.buffer_atr_mult": {"type": "float", "min": 0.07, "max": 0.16, "step": 0.01},
        "levels.h1.box_range_atr_mult": {"type": "float", "min": 1.0, "max": 1.8, "step": 0.1},
        "regime.d1.adx_trend_min": {"type": "int", "min": 20, "max": 27, "step": 1},
        "regime.d1.er_trend_min": {"type": "float", "min": 0.20, "max": 0.35, "step": 0.01},
        "regime.h1.dir_band_atr_mult": {"type": "float", "min": 0.15, "max": 0.30, "step": 0.01},
        "setups.require_vol_not_low": [True, False],
        "setups.rr_default": {"type": "float", "min": 1.4, "max": 2.2, "step": 0.1},
        "setups.pullback_max_dist_atr_mult": {"type": "float", "min": 0.6, "max": 1.2, "step": 0.1},
        "setups.max_risk_atr_mult": {"type": "float", "min": 0.9, "max": 1.4, "step": 0.1},
        "setups.sl_atr_mult": {"type": "float", "min": 0.7, "max": 1.0, "step": 0.1},
        "setups.min_rr_net": {"type": "float", "min": 1.0, "max": 1.4, "step": 0.1},
        "setups.min_reward_net_ticks": {"type": "float", "min": 1.0, "max": 4.0, "step": 1.0},
        "setups.min_reward_gross_ticks": {"type": "float", "min": 10.0, "max": 22.0, "step": 2.0},
        "setups.min_target_return_pct": {"type": "float", "min": 0.5, "max": 0.9, "step": 0.1},
        "setups.min_atr_h1_cost_mult": {"type": "float", "min": 4.0, "max": 8.0, "step": 1.0},
        "setups.min_atr_d1_cost_mult": {"type": "float", "min": 8.0, "max": 14.0, "step": 2.0},
    },
}

COST_MODEL_PROFILES: tuple[str, ...] = ("fixed_v1", "train_proxy_v1")

COMPARISON_POINTS: list[str] = [
    "setups_total",
    "filled_trades",
    "fill_rate",
    "tp_rate",
    "sl_rate",
    "exit_rate",
    "win_rate_net",
    "expectancy_net_ticks",
    "net_ticks_sum",
]


@dataclass(frozen=True)
class TrainSelectionMetrics:
    robust_score: float
    median_expectancy: float
    mad_expectancy: float
    instruments_with_trades: int
    robust_instruments: int


@dataclass(frozen=True)
class CostAssumptions:
    commission_ticks_per_side: float
    slippage_ticks_per_side: float
    spread_half_ticks: float

    @property
    def round_trip_ticks(self) -> float:
        return 2.0 * (
            float(self.commission_ticks_per_side)
            + float(self.slippage_ticks_per_side)
            + float(self.spread_half_ticks)
        )


@dataclass(frozen=True)
class SetupResult:
    instrument_id: str
    trade_date: str
    setup_id: str
    setup_kind: str
    side: str
    as_of_ts: str
    entry_ts: str | None
    exit_ts: str | None
    filled: bool
    outcome: str
    gross_ticks: float
    net_ticks: float
    cost_ticks: float
    entry_ticks: int | None
    exit_ticks: int | None
    gate_status: str | None = None
    gate_reason: str | None = None
    gate_expected_return_ticks: float | None = None
    gate_n_effective: float | None = None
    gate_p_tp: float | None = None
    gate_p_sl: float | None = None
    gate_p_exit: float | None = None


@dataclass(frozen=True)
class ProbHistoryEvent:
    ts: datetime
    context_key: tuple[str, str, str]
    outcome: str


@dataclass(frozen=True)
class ProbabilityGateConfig:
    enabled: bool
    min_n_effective: float
    min_expected_return_ticks: float
    half_life_days: float
    dirichlet_alpha: float
    context_mode: str


@dataclass(frozen=True)
class GoalConstraints:
    min_trades_per_week: float
    max_trades_per_week: float
    trade_freq_penalty: float


@dataclass(frozen=True)
class HpoTrialState:
    params: dict[str, Any]
    objective: float


@dataclass(frozen=True)
class EvalBaseSlice:
    d1: list[Candle]
    h1: list[Candle]
    m5: list[Candle]
    last_price_ticks: int


@dataclass
class WindowEvalCache:
    provider: InMemoryCandleProvider
    base_slice_cache: dict[tuple[Any, ...], EvalBaseSlice]
    regime_cache: dict[tuple[Any, ...], RegimeState]
    d1_levels_cache: dict[tuple[Any, ...], list[Level]]
    h1_levels_cache: dict[tuple[Any, ...], list[Level]]
    execution_cache: dict[tuple[Any, ...], ExecutionParams]
    regime_engines: dict[str, RegimeEngine]
    level_engines: dict[str, LevelEngine]
    execution_engines: dict[str, ExecutionEngine]
    setup_generators: dict[tuple[str, str], SetupGenerator]


@dataclass(frozen=True)
class ContractSpan:
    secid: str
    root: str
    first_date: date
    last_date: date


class FrontContractSelector:
    def __init__(self, *, spans_by_root: dict[str, list[ContractSpan]], roll_avoid_expiry_days: int) -> None:
        self._spans_by_root = {
            root: sorted(
                rows,
                key=lambda item: (item.last_date, item.first_date, item.secid),
            )
            for root, rows in spans_by_root.items()
            if rows
        }
        self._roll_avoid_expiry_days = max(int(roll_avoid_expiry_days), 0)

    @property
    def reporting_ids(self) -> list[str]:
        return sorted(self._spans_by_root.keys())

    @property
    def spans_by_root(self) -> dict[str, list[ContractSpan]]:
        return {root: list(rows) for root, rows in self._spans_by_root.items()}

    @property
    def roll_avoid_expiry_days(self) -> int:
        return int(self._roll_avoid_expiry_days)

    def resolve_day(self, day: date) -> list[tuple[str, str]]:
        resolved: list[tuple[str, str]] = []
        for root, rows in self._spans_by_root.items():
            secid = self._select_contract_for_day(rows, day)
            if secid is None:
                continue
            resolved.append((root, secid))
        return resolved

    def _select_contract_for_day(self, rows: list[ContractSpan], day: date) -> str | None:
        safe_rows = [
            item
            for item in rows
            if item.first_date <= day <= (item.last_date - timedelta(days=self._roll_avoid_expiry_days))
        ]
        if safe_rows:
            return str(safe_rows[0].secid)
        active_rows = [item for item in rows if item.first_date <= day <= item.last_date]
        if active_rows:
            return str(active_rows[0].secid)
        upcoming_rows = [item for item in rows if day < item.first_date]
        if upcoming_rows:
            return str(upcoming_rows[0].secid)
        return None


def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(str(value).strip())


def _parse_hhmm(value: str) -> time:
    return time.fromisoformat(str(value).strip())


def _iter_days(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _to_local_ts(raw: str, tz: ZoneInfo) -> datetime:
    normalized = str(raw).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _to_epoch_seconds(ts: datetime) -> int:
    if ts.tzinfo is None:
        return int(ts.timestamp())
    return int(ts.astimezone(ZoneInfo("UTC")).timestamp())


def _date_start_epoch(day: date, tz: ZoneInfo) -> int:
    return _to_epoch_seconds(datetime.combine(day, time(0, 0), tzinfo=tz))


def _date_end_epoch(day: date, tz: ZoneInfo) -> int:
    return _to_epoch_seconds(datetime.combine(day, time(23, 59, 59), tzinfo=tz))


def _epoch_to_local_date(epoch_seconds: int, tz: ZoneInfo) -> date:
    return datetime.fromtimestamp(int(epoch_seconds), tz=ZoneInfo("UTC")).astimezone(tz).date()


def _open_cache_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS iss_candles_cache (
            engine TEXT NOT NULL,
            market TEXT NOT NULL,
            board TEXT NOT NULL,
            secid TEXT NOT NULL,
            interval INTEGER NOT NULL,
            ts_epoch INTEGER NOT NULL,
            ts_iso TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            PRIMARY KEY (engine, market, board, secid, interval, ts_epoch)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_iss_candles_cache_lookup
        ON iss_candles_cache (engine, market, board, secid, interval, ts_epoch)
        """
    )
    conn.commit()
    return conn


def _cache_key(board: str | None) -> str:
    return str(board or "")


def _cache_range(
    *,
    conn: sqlite3.Connection,
    engine: str,
    market: str,
    board: str | None,
    secid: str,
    interval: int,
) -> tuple[int | None, int | None]:
    row = conn.execute(
        """
        SELECT MIN(ts_epoch), MAX(ts_epoch)
        FROM iss_candles_cache
        WHERE engine = ? AND market = ? AND board = ? AND secid = ? AND interval = ?
        """,
        (engine, market, _cache_key(board), secid, int(interval)),
    ).fetchone()
    if row is None:
        return (None, None)
    low = None if row[0] is None else int(row[0])
    high = None if row[1] is None else int(row[1])
    return (low, high)


def _cache_load(
    *,
    conn: sqlite3.Connection,
    engine: str,
    market: str,
    board: str | None,
    secid: str,
    interval: int,
    epoch_from: int,
    epoch_to: int,
) -> list[Candle]:
    rows = conn.execute(
        """
        SELECT ts_iso, open, high, low, close, volume
        FROM iss_candles_cache
        WHERE engine = ? AND market = ? AND board = ? AND secid = ? AND interval = ?
          AND ts_epoch >= ? AND ts_epoch <= ?
        ORDER BY ts_epoch ASC
        """,
        (
            engine,
            market,
            _cache_key(board),
            secid,
            int(interval),
            int(epoch_from),
            int(epoch_to),
        ),
    ).fetchall()
    output: list[Candle] = []
    for ts_iso, open_v, high_v, low_v, close_v, volume_v in rows:
        ts = datetime.fromisoformat(str(ts_iso))
        output.append(
            Candle(
                ts=ts,
                open=float(open_v),
                high=float(high_v),
                low=float(low_v),
                close=float(close_v),
                volume=float(volume_v),
            )
        )
    return output


def _cache_upsert(
    *,
    conn: sqlite3.Connection,
    engine: str,
    market: str,
    board: str | None,
    secid: str,
    interval: int,
    candles: list[Candle],
) -> int:
    if not candles:
        return 0
    rows = []
    for candle in candles:
        ts_epoch = _to_epoch_seconds(candle.ts)
        rows.append(
            (
                engine,
                market,
                _cache_key(board),
                secid,
                int(interval),
                int(ts_epoch),
                candle.ts.isoformat(),
                float(candle.open),
                float(candle.high),
                float(candle.low),
                float(candle.close),
                float(candle.volume),
            )
        )
    conn.executemany(
        """
        INSERT INTO iss_candles_cache (
            engine, market, board, secid, interval, ts_epoch, ts_iso, open, high, low, close, volume
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(engine, market, board, secid, interval, ts_epoch) DO UPDATE SET
            ts_iso = excluded.ts_iso,
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def _fetch_candles(
    *,
    client: MoexIssClient,
    engine: str,
    market: str,
    board: str,
    secid: str,
    date_from: date,
    date_to: date,
    interval: int,
    tz: ZoneInfo,
) -> list[Candle]:
    rows = client.get_candles(
        engine=engine,
        market=market,
        secid=secid,
        board=board,
        from_date=date_from,
        till_date=date_to,
        interval=interval,
    )
    candles: list[Candle] = []
    for row in rows:
        begin = row.get("begin")
        if begin is None:
            continue
        ts = _to_local_ts(str(begin), tz)
        candles.append(
            Candle(
                ts=ts,
                open=float(row.get("open", 0.0)),
                high=float(row.get("high", 0.0)),
                low=float(row.get("low", 0.0)),
                close=float(row.get("close", 0.0)),
                volume=float(row.get("value", row.get("volume", 0.0)) or 0.0),
            )
        )
    candles.sort(key=lambda item: item.ts)
    return candles


def _fetch_candles_cached(
    *,
    conn: sqlite3.Connection,
    client: MoexIssClient,
    engine: str,
    market: str,
    board: str,
    secid: str,
    date_from: date,
    date_to: date,
    interval: int,
    tz: ZoneInfo,
    offline_only: bool,
    refresh_cache: bool,
    stats: dict[str, int],
) -> list[Candle]:
    required_from_epoch = _date_start_epoch(date_from, tz)
    required_to_epoch = _date_end_epoch(date_to, tz)

    min_cached, max_cached = _cache_range(
        conn=conn,
        engine=engine,
        market=market,
        board=board,
        secid=secid,
        interval=interval,
    )
    needs_fetch = refresh_cache or min_cached is None or max_cached is None
    missing_ranges: list[tuple[date, date]] = []
    if needs_fetch:
        missing_ranges.append((date_from, date_to))
    else:
        min_cached_day = _epoch_to_local_date(min_cached, tz)
        max_cached_day = _epoch_to_local_date(max_cached, tz)
        if date_from < min_cached_day:
            missing_ranges.append((date_from, min_cached_day - timedelta(days=1)))
        if date_to > max_cached_day:
            missing_ranges.append((max_cached_day + timedelta(days=1), date_to))

    if missing_ranges:
        if offline_only:
            cached = _cache_load(
                conn=conn,
                engine=engine,
                market=market,
                board=board,
                secid=secid,
                interval=interval,
                epoch_from=required_from_epoch,
                epoch_to=required_to_epoch,
            )
            if cached:
                stats["cache_rows_loaded"] += len(cached)
                return cached
            raise ValueError(
                f"cache_miss_offline_mode:{secid}:interval={interval}:from={date_from.isoformat()}:to={date_to.isoformat()}"
            )
        for fetch_from, fetch_to in missing_ranges:
            if fetch_to < fetch_from:
                continue
            fetched = _fetch_candles(
                client=client,
                engine=engine,
                market=market,
                board=board,
                secid=secid,
                date_from=fetch_from,
                date_to=fetch_to,
                interval=interval,
                tz=tz,
            )
            stats["network_fetch_calls"] += 1
            stats["network_rows"] += len(fetched)
            stats["cache_rows_written"] += _cache_upsert(
                conn=conn,
                engine=engine,
                market=market,
                board=board,
                secid=secid,
                interval=interval,
                candles=fetched,
            )

    cached = _cache_load(
        conn=conn,
        engine=engine,
        market=market,
        board=board,
        secid=secid,
        interval=interval,
        epoch_from=required_from_epoch,
        epoch_to=required_to_epoch,
    )
    stats["cache_rows_loaded"] += len(cached)
    return cached


def _build_calendar(settings: AppSettings) -> MarketCalendar:
    cfg = settings.signal_engine.morning_plan
    calendar_cfg = cfg.calendar
    return MarketCalendar(
        tz_name=cfg.timezone,
        sessions=[parse_time_window(item.start, item.end) for item in calendar_cfg.sessions],
        clearing=[parse_time_window(item.start, item.end) for item in calendar_cfg.clearing_windows],
        forbid_margin_min=int(calendar_cfg.forbid_new_positions_margin_min),
    )


def _build_client(settings: AppSettings) -> MoexIssClient:
    return MoexIssClient(
        settings.moex.base_url,
        settings.moex.request_timeout_sec,
        max_retries=settings.moex.request_max_retries,
        retry_backoff_sec=settings.moex.request_retry_backoff_sec,
        retry_max_backoff_sec=settings.moex.request_retry_max_backoff_sec,
        fallback_ips=settings.moex.fallback_ips,
        force_fallback=settings.moex.force_fallback,
    )


def _resolve_tick_sizes(
    *,
    client: MoexIssClient,
    board: str,
    instruments: list[str],
    explicit: dict[str, float],
) -> dict[str, float]:
    rows = client.get_futures_specs(board)
    by_secid = {str(row.get("SECID")): row for row in rows}
    by_group_steps: dict[str, list[float]] = {}
    for row in rows:
        secid_raw = row.get("SECID")
        if secid_raw is None:
            continue
        group = _instrument_group(str(secid_raw))
        minstep = row.get("MINSTEP")
        try:
            step = float(minstep)
        except (TypeError, ValueError):
            continue
        if step <= 0:
            continue
        by_group_steps.setdefault(group, []).append(step)
    resolved: dict[str, float] = {}
    for instrument_id in instruments:
        if instrument_id in explicit:
            resolved[instrument_id] = float(explicit[instrument_id])
            continue
        row = by_secid.get(instrument_id)
        minstep = None if row is None else row.get("MINSTEP")
        try:
            tick_size = float(minstep)
        except (TypeError, ValueError):
            group = _instrument_group(instrument_id)
            group_steps = by_group_steps.get(group, [])
            tick_size = float(statistics.median(group_steps)) if group_steps else 0.01
        if tick_size <= 0:
            group = _instrument_group(instrument_id)
            group_steps = by_group_steps.get(group, [])
            tick_size = float(statistics.median(group_steps)) if group_steps else 0.01
        resolved[instrument_id] = tick_size
    return resolved


def _build_inmemory_payload(
    *,
    client: MoexIssClient,
    calendar: MarketCalendar,
    settings: AppSettings,
    instruments: list[str],
    date_from: date,
    date_to: date,
    cache_db_path: Path | None,
    use_cache: bool,
    offline_only: bool,
    refresh_cache: bool,
    allow_missing_cache: bool = False,
) -> tuple[dict[tuple[str, TF], list[Candle]], dict[str, int]]:
    payload: dict[tuple[str, TF], list[Candle]] = {}
    stats = {
        "network_fetch_calls": 0,
        "network_rows": 0,
        "cache_rows_loaded": 0,
        "cache_rows_written": 0,
    }
    tz = ZoneInfo(settings.signal_engine.morning_plan.timezone)
    conn = _open_cache_db(cache_db_path) if (use_cache and cache_db_path is not None) else None
    for instrument_id in instruments:
        fetch_args = {
            "client": client,
            "engine": settings.moex.engine_futures,
            "market": settings.moex.market_futures,
            "board": settings.moex.futures_board,
            "secid": instrument_id,
            "date_from": date_from,
            "date_to": date_to,
            "tz": tz,
        }
        if conn is not None:
            def _cached_or_empty(interval: int) -> list[Candle]:
                try:
                    return _fetch_candles_cached(
                        conn=conn,
                        interval=interval,
                        offline_only=offline_only,
                        refresh_cache=refresh_cache,
                        stats=stats,
                        **fetch_args,
                    )
                except ValueError as err:
                    if bool(allow_missing_cache) and str(err).startswith("cache_miss_offline_mode:"):
                        return []
                    raise

            d1 = _cached_or_empty(24)
            h1 = _cached_or_empty(60)
            m1 = _cached_or_empty(1)
        else:
            d1 = _fetch_candles(interval=24, **fetch_args)
            h1 = _fetch_candles(interval=60, **fetch_args)
            m1 = _fetch_candles(interval=1, **fetch_args)
            stats["network_fetch_calls"] += 3
            stats["network_rows"] += len(d1) + len(h1) + len(m1)
        m5 = resample_ohlcv(m1, target_tf=TF.M5, calendar=calendar)
        payload[(instrument_id, TF.D1)] = d1
        payload[(instrument_id, TF.H1)] = h1
        payload[(instrument_id, TF.M5)] = m5
    if conn is not None:
        conn.close()
    return payload, stats


def _expand_grid(grid: dict[str, list[float]]) -> list[dict[str, float]]:
    if not grid:
        return [{}]
    keys = sorted(grid.keys())
    values = [grid[key] for key in keys]
    combinations: list[dict[str, float]] = []
    for row in itertools.product(*values):
        combinations.append({key: float(value) for key, value in zip(keys, row)})
    return combinations


def _resolve_tuning_grid(profile_name: str) -> dict[str, list[float]]:
    key = str(profile_name or "baseline_v1").strip()
    if key not in TUNING_GRID_PROFILES:
        allowed = ",".join(sorted(TUNING_GRID_PROFILES.keys()))
        raise ValueError(f"unknown_tuning_profile:{key};allowed={allowed}")
    return copy.deepcopy(TUNING_GRID_PROFILES[key])


def _resolve_search_space(profile_name: str) -> dict[str, Any]:
    key = str(profile_name or "intraday_goal_v1").strip()
    if key not in TUNING_SEARCH_SPACE_PROFILES:
        allowed = ",".join(sorted(TUNING_SEARCH_SPACE_PROFILES.keys()))
        raise ValueError(f"unknown_search_space_profile:{key};allowed={allowed}")
    return copy.deepcopy(TUNING_SEARCH_SPACE_PROFILES[key])


def _resolve_search_algorithm(name: str) -> str:
    key = str(name or "GRID").strip().upper()
    if key not in {"GRID", "RANDOM", "TPE"}:
        raise ValueError("unknown_search_algorithm")
    return key


def _resolve_cost_model_profile(profile_name: str) -> str:
    key = str(profile_name or "fixed_v1").strip()
    if key not in COST_MODEL_PROFILES:
        allowed = ",".join(COST_MODEL_PROFILES)
        raise ValueError(f"unknown_cost_model_profile:{key};allowed={allowed}")
    return key


def _trades_per_week(*, filled_trades: int, period_start: date, period_end: date) -> float:
    days = (period_end - period_start).days + 1
    if days <= 0:
        return 0.0
    return float(max(int(filled_trades), 0) * 7.0 / float(days))


def _goal_adjusted_selection_score(
    *,
    base_score: float,
    summary: dict[str, Any],
    period_start: date,
    period_end: date,
    goal: GoalConstraints,
) -> float:
    weekly = _trades_per_week(
        filled_trades=int(summary.get("filled_trades", 0) or 0),
        period_start=period_start,
        period_end=period_end,
    )
    under = max(float(goal.min_trades_per_week) - float(weekly), 0.0)
    over = max(float(weekly) - float(goal.max_trades_per_week), 0.0)
    penalty = float(goal.trade_freq_penalty) * float(under + over)
    return float(base_score - penalty)


def _instrument_group(instrument_id: str) -> str:
    secid = str(instrument_id or "").strip()
    matched = re.match(r"^([A-Za-z0-9]+?)[FGHJKMNQUVXZ]\d$", secid)
    if matched:
        return str(matched.group(1)).upper()
    return secid.upper()


def _build_front_selector(
    *,
    instruments: list[str],
    payload: dict[tuple[str, TF], list[Candle]],
    roll_avoid_expiry_days: int,
) -> FrontContractSelector:
    spans_by_root: dict[str, list[ContractSpan]] = {}
    for secid in instruments:
        rows = payload.get((secid, TF.M5), [])
        if not rows:
            rows = payload.get((secid, TF.H1), [])
        if not rows:
            rows = payload.get((secid, TF.D1), [])
        if not rows:
            continue
        first_date = rows[0].ts.date()
        last_date = rows[-1].ts.date()
        if last_date < first_date:
            continue
        root = _instrument_group(secid)
        spans_by_root.setdefault(root, []).append(
            ContractSpan(
                secid=str(secid),
                root=str(root),
                first_date=first_date,
                last_date=last_date,
            )
        )
    return FrontContractSelector(
        spans_by_root=spans_by_root,
        roll_avoid_expiry_days=max(int(roll_avoid_expiry_days), 0),
    )


def _probability_context_key(*, setup: Setup, instrument_id: str, mode: str) -> tuple[str, str, str]:
    normalized = str(mode or "setup_kind").strip().lower()
    if normalized == "setup_group_side":
        return (_setup_kind(setup), _instrument_group(instrument_id), setup.side.value)
    return (_setup_kind(setup), "ALL", "ALL")


def _event_weight(age_days: float, half_life_days: float) -> float:
    halflife = max(float(half_life_days), 1e-9)
    age = max(float(age_days), 0.0)
    return float(math.exp(-math.log(2.0) * age / halflife))


def _probability_forecast(
    *,
    as_of_ts: datetime,
    context_key: tuple[str, str, str],
    history: list[ProbHistoryEvent],
    dirichlet_alpha: float,
    half_life_days: float,
) -> dict[str, float]:
    alpha = max(float(dirichlet_alpha), 1e-9)
    n_tp = 0.0
    n_sl = 0.0
    n_exit = 0.0
    weights: list[float] = []
    for event in history:
        if event.context_key != context_key:
            continue
        if event.ts > as_of_ts:
            continue
        age_days = (as_of_ts - event.ts).total_seconds() / 86400.0
        weight = _event_weight(age_days, half_life_days)
        weights.append(weight)
        if event.outcome == "TP":
            n_tp += weight
        elif event.outcome == "SL":
            n_sl += weight
        else:
            n_exit += weight
    total = n_tp + n_sl + n_exit
    denom = total + 3.0 * alpha
    p_tp = (n_tp + alpha) / denom
    p_sl = (n_sl + alpha) / denom
    p_exit = (n_exit + alpha) / denom
    if not weights:
        n_effective = 0.0
    else:
        sum_w = sum(weights)
        sum_w_sq = sum(value * value for value in weights)
        n_effective = float((sum_w * sum_w) / max(sum_w_sq, 1e-12))
    return {
        "p_tp": float(p_tp),
        "p_sl": float(p_sl),
        "p_exit": float(p_exit),
        "n_effective": float(n_effective),
    }


def _expected_return_from_forecast(
    *,
    setup: Setup,
    costs: CostAssumptions,
    forecast: dict[str, float],
) -> float:
    entry_ticks = int(setup.entry_order.price_ticks)
    tp_ticks = int(setup.tp_order.price_ticks)
    sl_ticks = int(setup.sl_order.price_ticks)
    reward_gross = abs(int(tp_ticks) - int(entry_ticks))
    risk_gross = abs(int(entry_ticks) - int(sl_ticks))
    expectancy = (
        float(forecast.get("p_tp", 0.0)) * float(reward_gross)
        + float(forecast.get("p_sl", 0.0)) * float(-risk_gross)
        + float(forecast.get("p_exit", 0.0)) * 0.0
    )
    return float(expectancy - float(costs.round_trip_ticks))


def _gated_out_result(
    *,
    instrument_id: str,
    as_of_ts: datetime,
    setup: Setup,
    reason: str,
    expected_return_ticks: float,
    forecast: dict[str, float],
) -> SetupResult:
    return SetupResult(
        instrument_id=instrument_id,
        trade_date=as_of_ts.date().isoformat(),
        setup_id=setup.setup_id,
        setup_kind=_setup_kind(setup),
        side=setup.side.value,
        as_of_ts=as_of_ts.isoformat(),
        entry_ts=None,
        exit_ts=None,
        filled=False,
        outcome="GATED_OUT",
        gross_ticks=0.0,
        net_ticks=0.0,
        cost_ticks=0.0,
        entry_ticks=None,
        exit_ticks=None,
        gate_status="BLOCK",
        gate_reason=str(reason),
        gate_expected_return_ticks=float(expected_return_ticks),
        gate_n_effective=float(forecast.get("n_effective", 0.0)),
        gate_p_tp=float(forecast.get("p_tp", 0.0)),
        gate_p_sl=float(forecast.get("p_sl", 0.0)),
        gate_p_exit=float(forecast.get("p_exit", 0.0)),
    )


def _value_rank(value: float, samples: list[float]) -> float:
    finite = [float(item) for item in samples if float(item) == float(item)]
    if not finite:
        return 0.5
    sorted_values = sorted(finite)
    count = len(sorted_values)
    index = 0
    for idx, item in enumerate(sorted_values):
        if value <= item:
            index = idx
            break
    else:
        index = count - 1
    return float(index / max(count - 1, 1))


def _derive_fold_instrument_costs(
    *,
    instruments: list[str],
    payload: dict[tuple[str, TF], list[Candle]],
    tick_sizes: dict[str, float],
    train_start: date,
    train_end: date,
    base_costs: CostAssumptions,
    profile: str,
) -> dict[str, CostAssumptions]:
    if profile == "fixed_v1":
        return {instrument_id: base_costs for instrument_id in instruments}

    med_volume_by_instrument: dict[str, float] = {}
    med_range_ticks_by_instrument: dict[str, float] = {}
    for instrument_id in instruments:
        rows = payload.get((instrument_id, TF.M5), [])
        train_rows = [row for row in rows if train_start <= row.ts.date() <= train_end]
        if not train_rows:
            continue
        volumes = [float(max(row.volume, 0.0)) for row in train_rows]
        tick_size = float(tick_sizes[instrument_id])
        ranges_ticks = [
            float(max(price_to_ticks(float(row.high) - float(row.low), tick_size), 0))
            for row in train_rows
        ]
        if volumes:
            med_volume_by_instrument[instrument_id] = float(statistics.median(volumes))
        if ranges_ticks:
            med_range_ticks_by_instrument[instrument_id] = float(statistics.median(ranges_ticks))

    volume_samples = list(med_volume_by_instrument.values())
    result: dict[str, CostAssumptions] = {}
    for instrument_id in instruments:
        med_volume = med_volume_by_instrument.get(instrument_id)
        med_range_ticks = med_range_ticks_by_instrument.get(instrument_id)
        if med_volume is None or med_range_ticks is None:
            result[instrument_id] = base_costs
            continue
        volume_rank = _value_rank(float(med_volume), volume_samples)
        if volume_rank <= 0.33:
            spread_half = 1.5
        elif volume_rank <= 0.66:
            spread_half = 1.25
        else:
            spread_half = 1.0

        slippage = float(base_costs.slippage_ticks_per_side)
        if med_range_ticks >= 30.0:
            slippage += 0.5
        elif med_range_ticks >= 15.0:
            slippage += 0.25
        if volume_rank <= 0.33:
            slippage += 0.25
        slippage = min(max(slippage, 0.5), 3.0)
        result[instrument_id] = CostAssumptions(
            commission_ticks_per_side=float(base_costs.commission_ticks_per_side),
            slippage_ticks_per_side=float(slippage),
            spread_half_ticks=float(spread_half),
        )
    return result


def _apply_overrides(base_cfg: dict[str, Any], overrides: dict[str, float]) -> dict[str, Any]:
    cfg = copy.deepcopy(base_cfg)
    for dotted_path, value in overrides.items():
        parts = dotted_path.split(".")
        cursor: dict[str, Any] = cfg
        for part in parts[:-1]:
            nested = cursor.get(part)
            if not isinstance(nested, dict):
                nested = {}
                cursor[part] = nested
            cursor = nested
        cursor[parts[-1]] = value
    return cfg


def _horizon_deadline(as_of_ts: datetime, horizon: str, calendar: MarketCalendar) -> datetime:
    normalized = str(horizon or "EOD").upper()
    if normalized == "NEXT_DAY_EOD":
        return calendar.recommended_entry_expiry(as_of_ts + timedelta(days=1), "EOD_BEFORE_EVENING_CLEARING")
    return calendar.recommended_entry_expiry(as_of_ts, "EOD_BEFORE_EVENING_CLEARING")


def _order_type_name(setup: Setup) -> str:
    order_type = setup.entry_order.order_type
    if hasattr(order_type, "value"):
        return str(order_type.value).upper()
    return str(order_type).upper()


def _setup_kind(setup: Setup) -> str:
    raw = setup.entry_order.meta.get("setup_kind")
    if isinstance(raw, str) and raw:
        return raw
    return "UNKNOWN"


def _entry_fill(
    *,
    setup: Setup,
    bars: list[Candle],
    tick_size: float,
) -> tuple[datetime, int] | None:
    side = setup.side
    entry_ticks = int(setup.entry_order.price_ticks)
    order_type = _order_type_name(setup)

    if order_type == "LIMIT":
        for bar in bars:
            high_ticks = price_to_ticks(float(bar.high), tick_size)
            low_ticks = price_to_ticks(float(bar.low), tick_size)
            if side == Side.BUY and low_ticks <= entry_ticks:
                return bar.ts, entry_ticks
            if side == Side.SELL and high_ticks >= entry_ticks:
                return bar.ts, entry_ticks
        return None

    if order_type == "STOP":
        for bar in bars:
            high_ticks = price_to_ticks(float(bar.high), tick_size)
            low_ticks = price_to_ticks(float(bar.low), tick_size)
            if side == Side.BUY and high_ticks >= entry_ticks:
                return bar.ts, entry_ticks
            if side == Side.SELL and low_ticks <= entry_ticks:
                return bar.ts, entry_ticks
        return None

    if order_type == "STOP_LIMIT":
        raw_limit = setup.entry_order.meta.get("limit_price_ticks")
        try:
            limit_ticks = int(raw_limit) if raw_limit is not None else int(entry_ticks)
        except (TypeError, ValueError):
            limit_ticks = int(entry_ticks)
        triggered = False
        for bar in bars:
            high_ticks = price_to_ticks(float(bar.high), tick_size)
            low_ticks = price_to_ticks(float(bar.low), tick_size)
            if not triggered:
                if side == Side.BUY and high_ticks >= entry_ticks:
                    triggered = True
                if side == Side.SELL and low_ticks <= entry_ticks:
                    triggered = True
            if not triggered:
                continue
            if side == Side.BUY and low_ticks <= limit_ticks:
                return bar.ts, int(limit_ticks)
            if side == Side.SELL and high_ticks >= limit_ticks:
                return bar.ts, int(limit_ticks)
        return None

    return None


def _exit_result(
    *,
    setup: Setup,
    bars: list[Candle],
    tick_size: float,
    fill_ts: datetime,
    fill_ticks: int,
) -> tuple[str, datetime, int]:
    tp_ticks = int(setup.tp_order.price_ticks)
    sl_ticks = int(setup.sl_order.price_ticks)
    for bar in bars:
        if bar.ts <= fill_ts:
            continue
        high_ticks = price_to_ticks(float(bar.high), tick_size)
        low_ticks = price_to_ticks(float(bar.low), tick_size)
        if setup.side == Side.BUY:
            tp_hit = high_ticks >= tp_ticks
            sl_hit = low_ticks <= sl_ticks
        else:
            tp_hit = low_ticks <= tp_ticks
            sl_hit = high_ticks >= sl_ticks
        if tp_hit and sl_hit:
            return "SL", bar.ts, sl_ticks
        if tp_hit:
            return "TP", bar.ts, tp_ticks
        if sl_hit:
            return "SL", bar.ts, sl_ticks
    if not bars:
        return "EXIT", fill_ts, int(fill_ticks)
    last = bars[-1]
    return "EXIT", last.ts, price_to_ticks(float(last.close), tick_size)


def _simulate_setup(
    *,
    instrument_id: str,
    as_of_ts: datetime,
    setup: Setup,
    m5_rows: list[Candle],
    tick_size: float,
    calendar: MarketCalendar,
    costs: CostAssumptions,
) -> SetupResult:
    entry_expiry = setup.entry_order.expire_ts or calendar.recommended_entry_expiry(
        as_of_ts, "EOD_BEFORE_EVENING_CLEARING"
    )
    horizon_deadline = _horizon_deadline(as_of_ts, setup.horizon, calendar)
    entry_deadline = min(entry_expiry, horizon_deadline)
    entry_bars = [bar for bar in m5_rows if as_of_ts < bar.ts <= entry_deadline]
    fill = _entry_fill(setup=setup, bars=entry_bars, tick_size=tick_size)
    if fill is None:
        return SetupResult(
            instrument_id=instrument_id,
            trade_date=as_of_ts.date().isoformat(),
            setup_id=setup.setup_id,
            setup_kind=_setup_kind(setup),
            side=setup.side.value,
            as_of_ts=as_of_ts.isoformat(),
            entry_ts=None,
            exit_ts=None,
            filled=False,
            outcome="NO_FILL",
            gross_ticks=0.0,
            net_ticks=0.0,
            cost_ticks=0.0,
            entry_ticks=None,
            exit_ticks=None,
        )
    fill_ts, fill_ticks = fill
    exit_bars = [bar for bar in m5_rows if fill_ts < bar.ts <= horizon_deadline]
    outcome, exit_ts, exit_ticks = _exit_result(
        setup=setup,
        bars=exit_bars,
        tick_size=tick_size,
        fill_ts=fill_ts,
        fill_ticks=fill_ticks,
    )
    side_sign = 1.0 if setup.side == Side.BUY else -1.0
    gross_ticks = side_sign * float(exit_ticks - fill_ticks)
    net_ticks = gross_ticks - costs.round_trip_ticks
    return SetupResult(
        instrument_id=instrument_id,
        trade_date=as_of_ts.date().isoformat(),
        setup_id=setup.setup_id,
        setup_kind=_setup_kind(setup),
        side=setup.side.value,
        as_of_ts=as_of_ts.isoformat(),
        entry_ts=fill_ts.isoformat(),
        exit_ts=exit_ts.isoformat(),
        filled=True,
        outcome=outcome,
        gross_ticks=float(gross_ticks),
        net_ticks=float(net_ticks),
        cost_ticks=float(costs.round_trip_ticks),
        entry_ticks=int(fill_ticks),
        exit_ticks=int(exit_ticks),
    )


def _summarize(results: list[SetupResult], setups_total: int) -> dict[str, Any]:
    filled = [row for row in results if row.filled]
    gated = [row for row in results if row.outcome == "GATED_OUT"]
    filled_count = len(filled)
    tp_count = sum(1 for row in filled if row.outcome == "TP")
    sl_count = sum(1 for row in filled if row.outcome == "SL")
    exit_count = sum(1 for row in filled if row.outcome == "EXIT")
    win_count = sum(1 for row in filled if row.net_ticks > 0.0)
    net_sum = float(sum(row.net_ticks for row in filled))
    gross_sum = float(sum(row.gross_ticks for row in filled))
    expectancy = net_sum / float(filled_count) if filled_count > 0 else 0.0
    fill_rate = float(filled_count / float(setups_total)) if setups_total > 0 else 0.0
    by_kind: dict[str, dict[str, float]] = {}
    by_instrument: dict[str, dict[str, float]] = {}
    for row in filled:
        slot = by_kind.setdefault(row.setup_kind, {"count": 0.0, "net_ticks_sum": 0.0})
        slot["count"] += 1.0
        slot["net_ticks_sum"] += float(row.net_ticks)
        inst_slot = by_instrument.setdefault(
            row.instrument_id,
            {
                "count": 0.0,
                "net_ticks_sum": 0.0,
                "tp_count": 0.0,
                "sl_count": 0.0,
                "exit_count": 0.0,
                "win_count": 0.0,
            },
        )
        inst_slot["count"] += 1.0
        inst_slot["net_ticks_sum"] += float(row.net_ticks)
        if row.outcome == "TP":
            inst_slot["tp_count"] += 1.0
        elif row.outcome == "SL":
            inst_slot["sl_count"] += 1.0
        elif row.outcome == "EXIT":
            inst_slot["exit_count"] += 1.0
        if row.net_ticks > 0.0:
            inst_slot["win_count"] += 1.0
    for kind, slot in by_kind.items():
        count = slot["count"]
        slot["expectancy_net_ticks"] = float(slot["net_ticks_sum"] / count) if count > 0 else 0.0
        slot["count"] = int(count)
        by_kind[kind] = slot
    for instrument_id, slot in by_instrument.items():
        count = slot["count"]
        slot["expectancy_net_ticks"] = float(slot["net_ticks_sum"] / count) if count > 0 else 0.0
        slot["tp_rate"] = float(slot["tp_count"] / count) if count > 0 else 0.0
        slot["sl_rate"] = float(slot["sl_count"] / count) if count > 0 else 0.0
        slot["exit_rate"] = float(slot["exit_count"] / count) if count > 0 else 0.0
        slot["win_rate_net"] = float(slot["win_count"] / count) if count > 0 else 0.0
        slot["count"] = int(count)
        slot["tp_count"] = int(slot["tp_count"])
        slot["sl_count"] = int(slot["sl_count"])
        slot["exit_count"] = int(slot["exit_count"])
        slot["win_count"] = int(slot["win_count"])
        by_instrument[instrument_id] = slot
    return {
        "setups_total": int(setups_total),
        "gated_out": int(len(gated)),
        "filled_trades": int(filled_count),
        "fill_rate": float(fill_rate),
        "tp_rate": float(tp_count / filled_count) if filled_count > 0 else 0.0,
        "sl_rate": float(sl_count / filled_count) if filled_count > 0 else 0.0,
        "exit_rate": float(exit_count / filled_count) if filled_count > 0 else 0.0,
        "win_rate_net": float(win_count / filled_count) if filled_count > 0 else 0.0,
        "expectancy_net_ticks": float(expectancy),
        "gross_ticks_sum": float(gross_sum),
        "net_ticks_sum": float(net_sum),
        "by_setup_kind": by_kind,
        "by_instrument": by_instrument,
    }


def _should_probability_gate_fallback(
    *,
    probability_gate_enabled: bool,
    min_filled_trades_per_fold: int,
    test_summary: dict[str, Any],
) -> bool:
    if not bool(probability_gate_enabled):
        return False
    threshold = max(int(min_filled_trades_per_fold), 0)
    if threshold <= 0:
        return False
    filled = int(test_summary.get("filled_trades", 0) or 0)
    return filled < threshold


def _train_selection_metrics(
    *,
    summary: dict[str, Any],
    min_trades_per_instrument: int,
    mad_penalty: float,
) -> TrainSelectionMetrics:
    by_instrument = summary.get("by_instrument")
    if not isinstance(by_instrument, dict):
        return TrainSelectionMetrics(
            robust_score=float("-inf"),
            median_expectancy=0.0,
            mad_expectancy=0.0,
            instruments_with_trades=0,
            robust_instruments=0,
        )
    instrument_rows = [item for item in by_instrument.values() if isinstance(item, dict)]
    instruments_with_trades = sum(1 for item in instrument_rows if int(item.get("count", 0) or 0) > 0)
    robust_expectancies = [
        float(item.get("expectancy_net_ticks", 0.0))
        for item in instrument_rows
        if int(item.get("count", 0) or 0) >= max(int(min_trades_per_instrument), 1)
    ]
    robust_instruments = len(robust_expectancies)
    if not robust_expectancies:
        return TrainSelectionMetrics(
            robust_score=float("-inf"),
            median_expectancy=0.0,
            mad_expectancy=0.0,
            instruments_with_trades=int(instruments_with_trades),
            robust_instruments=0,
        )
    median_expectancy = float(statistics.median(robust_expectancies))
    mad_expectancy = float(statistics.median(abs(value - median_expectancy) for value in robust_expectancies))
    robust_score = float(median_expectancy - max(float(mad_penalty), 0.0) * mad_expectancy)
    return TrainSelectionMetrics(
        robust_score=robust_score,
        median_expectancy=median_expectancy,
        mad_expectancy=mad_expectancy,
        instruments_with_trades=int(instruments_with_trades),
        robust_instruments=int(robust_instruments),
    )


def _stable_signature(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=str)


def _cfg_section(cfg: dict[str, Any], key: str) -> dict[str, Any]:
    item = cfg.get(key, {})
    return item if isinstance(item, dict) else {}


def _build_window_eval_cache(payload: dict[tuple[str, TF], list[Candle]]) -> WindowEvalCache:
    return WindowEvalCache(
        provider=InMemoryCandleProvider(payload),
        base_slice_cache={},
        regime_cache={},
        d1_levels_cache={},
        h1_levels_cache={},
        execution_cache={},
        regime_engines={},
        level_engines={},
        execution_engines={},
        setup_generators={},
    )


def _compute_setups_cached(
    *,
    eval_cache: WindowEvalCache,
    cfg: dict[str, Any],
    calendar: MarketCalendar,
    as_of_ts: datetime,
    instrument_id: str,
    tick_size: float,
) -> list[Setup]:
    data_cfg = _cfg_section(cfg, "data")
    d1_limit = int(data_cfg.get("d1_limit", 200))
    h1_limit = int(data_cfg.get("h1_limit", 300))
    m5_limit = int(data_cfg.get("m5_limit", 300))
    base_key = (
        str(instrument_id),
        as_of_ts.isoformat(),
        float(tick_size),
        int(d1_limit),
        int(h1_limit),
        int(m5_limit),
    )
    base_slice = eval_cache.base_slice_cache.get(base_key)
    if base_slice is None:
        d1 = eval_cache.provider.get_candles(instrument_id, TF.D1, as_of_ts, d1_limit)
        h1 = eval_cache.provider.get_candles(instrument_id, TF.H1, as_of_ts, h1_limit)
        m5 = eval_cache.provider.get_candles(instrument_id, TF.M5, as_of_ts, m5_limit)
        if m5:
            last_price_ticks = price_to_ticks(float(m5[-1].close), tick_size)
        elif h1:
            last_price_ticks = price_to_ticks(float(h1[-1].close), tick_size)
        elif d1:
            last_price_ticks = price_to_ticks(float(d1[-1].close), tick_size)
        else:
            last_price_ticks = 0
        base_slice = EvalBaseSlice(d1=d1, h1=h1, m5=m5, last_price_ticks=int(last_price_ticks))
        eval_cache.base_slice_cache[base_key] = base_slice

    regime_cfg = _cfg_section(cfg, "regime")
    regime_sig = _stable_signature(regime_cfg)
    regime_key = (base_key, regime_sig)
    regime = eval_cache.regime_cache.get(regime_key)
    if regime is None:
        regime_engine = eval_cache.regime_engines.get(regime_sig)
        if regime_engine is None:
            regime_engine = RegimeEngine(regime_cfg)
            eval_cache.regime_engines[regime_sig] = regime_engine
        regime = regime_engine.compute(
            as_of_ts=as_of_ts,
            d1=base_slice.d1,
            h1=base_slice.h1,
            m5=base_slice.m5,
            tick_size=tick_size,
            orderbook=None,
            calendar=calendar,
        )
        eval_cache.regime_cache[regime_key] = regime

    levels_cfg = _cfg_section(cfg, "levels")
    levels_sig = _stable_signature(levels_cfg)
    level_engine = eval_cache.level_engines.get(levels_sig)
    if level_engine is None:
        level_engine = LevelEngine(levels_cfg)
        eval_cache.level_engines[levels_sig] = level_engine

    d1_levels_key = (base_key, levels_sig, "D1")
    d1_levels = eval_cache.d1_levels_cache.get(d1_levels_key)
    if d1_levels is None:
        d1_levels = level_engine.compute_d1_levels(base_slice.d1, tick_size=tick_size)
        eval_cache.d1_levels_cache[d1_levels_key] = d1_levels

    h1_levels_key = (base_key, levels_sig, "H1")
    h1_levels = eval_cache.h1_levels_cache.get(h1_levels_key)
    if h1_levels is None:
        h1_levels = level_engine.compute_h1_levels(base_slice.h1, calendar=calendar, tick_size=tick_size)
        eval_cache.h1_levels_cache[h1_levels_key] = h1_levels

    execution_cfg = _cfg_section(cfg, "execution")
    execution_sig = _stable_signature(execution_cfg)
    execution_key = (base_key, execution_sig)
    exec_params = eval_cache.execution_cache.get(execution_key)
    execution_engine = eval_cache.execution_engines.get(execution_sig)
    if execution_engine is None:
        execution_engine = ExecutionEngine(execution_cfg)
        eval_cache.execution_engines[execution_sig] = execution_engine
    if exec_params is None:
        exec_params = execution_engine.compute_params(base_slice.m5, tick_size=tick_size)
        eval_cache.execution_cache[execution_key] = exec_params

    setups_cfg = _cfg_section(cfg, "setups")
    setups_sig = _stable_signature(setups_cfg)
    setup_key = (setups_sig, execution_sig)
    setup_generator = eval_cache.setup_generators.get(setup_key)
    if setup_generator is None:
        setup_generator = SetupGenerator(setups_cfg, execution_engine=execution_engine)
        eval_cache.setup_generators[setup_key] = setup_generator
    setups = setup_generator.generate(
        as_of_ts=as_of_ts,
        instrument_id=instrument_id,
        last_price_ticks=int(base_slice.last_price_ticks),
        regime=regime,
        levels_d1=d1_levels,
        levels_h1=h1_levels,
        exec_params=exec_params,
        calendar=calendar,
        m5=base_slice.m5,
    )
    return setups


def _build_train_score_row(
    *,
    combo: dict[str, Any],
    base_cfg: dict[str, Any],
    period_start: date,
    period_end: date,
    instruments: list[str],
    decision_time: time,
    tz: ZoneInfo,
    payload: dict[tuple[str, TF], list[Candle]],
    tick_sizes: dict[str, float],
    calendar: MarketCalendar,
    costs: CostAssumptions,
    instrument_costs: dict[str, CostAssumptions] | None,
    front_selector: FrontContractSelector | None,
    eval_cache: WindowEvalCache | None,
    train_probability_gate: ProbabilityGateConfig,
    min_trades_per_instrument: int,
    robust_mad_penalty: float,
    selection_objective: str,
    goal: GoalConstraints,
) -> dict[str, Any]:
    cfg = _apply_overrides(base_cfg, combo)
    _, train_summary, _ = _evaluate_window(
        period_start=period_start,
        period_end=period_end,
        instruments=instruments,
        decision_time=decision_time,
        tz=tz,
        cfg=cfg,
        payload=payload,
        tick_sizes=tick_sizes,
        calendar=calendar,
        costs=costs,
        instrument_costs=instrument_costs,
        front_selector=front_selector,
        eval_cache=eval_cache,
        probability_gate=train_probability_gate,
        collect_history=False,
    )
    metrics = asdict(
        _train_selection_metrics(
            summary=train_summary,
            min_trades_per_instrument=min_trades_per_instrument,
            mad_penalty=robust_mad_penalty,
        )
    )
    if selection_objective == "expectancy_net_ticks":
        base_score = float(train_summary.get("expectancy_net_ticks", 0.0))
    else:
        base_score = float(metrics.get("robust_score", float("-inf")))
    selection_score = _goal_adjusted_selection_score(
        base_score=base_score,
        summary=train_summary,
        period_start=period_start,
        period_end=period_end,
        goal=goal,
    )
    metrics["selection_score"] = float(selection_score)
    metrics["trades_per_week"] = _trades_per_week(
        filled_trades=int(train_summary.get("filled_trades", 0) or 0),
        period_start=period_start,
        period_end=period_end,
    )
    return {
        "params": combo,
        "summary": train_summary,
        "metrics": metrics,
    }


def _is_train_row_eligible(
    *,
    row: dict[str, Any],
    min_train_trades: int,
    required_instruments: int,
) -> bool:
    summary = row.get("summary", {})
    metrics = row.get("metrics", {})
    return bool(
        int(summary.get("filled_trades", 0) or 0) >= int(min_train_trades)
        and int(metrics.get("instruments_with_trades", 0) or 0) >= int(required_instruments)
        and int(metrics.get("robust_instruments", 0) or 0) >= int(required_instruments)
    )


def _evaluate_window(
    *,
    period_start: date,
    period_end: date,
    instruments: list[str],
    decision_time: time,
    tz: ZoneInfo,
    cfg: dict[str, Any],
    payload: dict[tuple[str, TF], list[Candle]],
    tick_sizes: dict[str, float],
    calendar: MarketCalendar,
    costs: CostAssumptions,
    instrument_costs: dict[str, CostAssumptions] | None = None,
    front_selector: FrontContractSelector | None = None,
    eval_cache: WindowEvalCache | None = None,
    probability_gate: ProbabilityGateConfig | None = None,
    initial_history: list[ProbHistoryEvent] | None = None,
    collect_history: bool = False,
) -> tuple[list[SetupResult], dict[str, Any], list[ProbHistoryEvent]]:
    builders: dict[str, MorningPlanBuilder] = {}
    if eval_cache is None:
        provider = InMemoryCandleProvider(payload)
        builders = {instrument_id: MorningPlanBuilder(provider, calendar, cfg) for instrument_id in instruments}
    rows: list[SetupResult] = []
    setups_total = 0
    history: list[ProbHistoryEvent] = list(initial_history or [])
    gate_mode = str(probability_gate.context_mode) if probability_gate is not None else "setup_kind"
    for day in _iter_days(period_start, period_end):
        as_of_ts = datetime.combine(day, decision_time, tzinfo=tz)
        if not calendar.is_trading_time(as_of_ts):
            continue
        day_targets = (
            front_selector.resolve_day(day)
            if front_selector is not None
            else [(instrument_id, instrument_id) for instrument_id in instruments]
        )
        for report_instrument_id, secid in day_targets:
            tick_size = float(tick_sizes[secid])
            effective_costs = costs if instrument_costs is None else instrument_costs.get(secid, costs)
            if eval_cache is None:
                builder = builders[secid]
                plan = builder.build_plan(as_of_ts=as_of_ts, instrument_id=secid, tick_size=tick_size)
                setups = plan.setups
            else:
                setups = _compute_setups_cached(
                    eval_cache=eval_cache,
                    cfg=cfg,
                    calendar=calendar,
                    as_of_ts=as_of_ts,
                    instrument_id=secid,
                    tick_size=tick_size,
                )
            m5_rows = payload.get((secid, TF.M5), [])
            setups_total += len(setups)
            for setup in setups:
                if probability_gate is not None and bool(probability_gate.enabled):
                    context_key = _probability_context_key(
                        setup=setup,
                        instrument_id=report_instrument_id,
                        mode=gate_mode,
                    )
                    forecast = _probability_forecast(
                        as_of_ts=as_of_ts,
                        context_key=context_key,
                        history=history,
                        dirichlet_alpha=float(probability_gate.dirichlet_alpha),
                        half_life_days=float(probability_gate.half_life_days),
                    )
                    expected_value = _expected_return_from_forecast(
                        setup=setup,
                        costs=effective_costs,
                        forecast=forecast,
                    )
                    if float(forecast.get("n_effective", 0.0)) < float(probability_gate.min_n_effective):
                        rows.append(
                            _gated_out_result(
                                instrument_id=report_instrument_id,
                                as_of_ts=as_of_ts,
                                setup=setup,
                                reason="low_n_effective",
                                expected_return_ticks=expected_value,
                                forecast=forecast,
                            )
                        )
                        continue
                    if float(expected_value) < float(probability_gate.min_expected_return_ticks):
                        rows.append(
                            _gated_out_result(
                                instrument_id=report_instrument_id,
                                as_of_ts=as_of_ts,
                                setup=setup,
                                reason="expected_return_below_threshold",
                                expected_return_ticks=expected_value,
                                forecast=forecast,
                            )
                        )
                        continue
                rows.append(
                    _simulate_setup(
                        instrument_id=report_instrument_id,
                        as_of_ts=as_of_ts,
                        setup=setup,
                        m5_rows=m5_rows,
                        tick_size=tick_size,
                        calendar=calendar,
                        costs=effective_costs,
                    )
                )
                latest = rows[-1]
                if bool(collect_history) and bool(latest.filled) and latest.outcome in {"TP", "SL", "EXIT"} and latest.exit_ts is not None:
                    history.append(
                        ProbHistoryEvent(
                            ts=datetime.fromisoformat(str(latest.exit_ts)),
                            context_key=_probability_context_key(
                                setup=setup,
                                instrument_id=report_instrument_id,
                                mode=gate_mode,
                            ),
                            outcome=str(latest.outcome),
                        )
                    )
    summary = _summarize(rows, setups_total=setups_total)
    return rows, summary, history


def _parse_tick_sizes(items: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"invalid_tick_size_pair:{item}")
        instrument_id, raw_tick = item.split("=", 1)
        key = instrument_id.strip()
        if not key:
            raise ValueError(f"invalid_tick_size_pair:{item}")
        value = float(raw_tick.strip())
        if value <= 0:
            raise ValueError(f"invalid_tick_size_pair:{item}")
        result[key] = value
    return result


def _fold_windows(
    *,
    start_date: date,
    end_date: date,
    train_days: int,
    test_days: int,
    step_days: int,
) -> list[dict[str, date]]:
    windows: list[dict[str, date]] = []
    cursor = start_date
    while cursor <= end_date:
        test_start = cursor
        test_end = min(end_date, test_start + timedelta(days=max(test_days, 1) - 1))
        train_end = test_start - timedelta(days=1)
        train_start = train_end - timedelta(days=max(train_days, 1) - 1)
        windows.append(
            {
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
            }
        )
        cursor = cursor + timedelta(days=max(step_days, 1))
    return windows


def run_walk_forward(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings(args.config)
    calendar = _build_calendar(settings)
    tz = ZoneInfo(settings.signal_engine.morning_plan.timezone)
    client = _build_client(settings)

    instruments = sorted(set(args.instrument))
    instrument_mode = str(args.instrument_mode or "fixed").strip().lower()
    if instrument_mode not in {"fixed", "front_nearest"}:
        raise ValueError("unknown_instrument_mode")
    front_roll_avoid_expiry_days = max(int(args.front_roll_avoid_expiry_days), 0)
    explicit_tick_sizes = _parse_tick_sizes(args.tick_size or [])
    tick_sizes = _resolve_tick_sizes(
        client=client,
        board=settings.moex.futures_board,
        instruments=instruments,
        explicit=explicit_tick_sizes,
    )

    start_date = _parse_iso_date(args.start_date)
    end_date = _parse_iso_date(args.end_date)
    if end_date < start_date:
        raise ValueError("end_date_before_start_date")
    decision_time = _parse_hhmm(args.decision_time)
    use_cache = not bool(args.no_cache)
    cache_db_path = Path(args.cache_db) if args.cache_db else None

    warmup_days = max(int(args.train_days) + 120, 180)
    preload_start = start_date - timedelta(days=warmup_days)
    preload_end = end_date + timedelta(days=2)
    payload, preload_stats = _build_inmemory_payload(
        client=client,
        calendar=calendar,
        settings=settings,
        instruments=instruments,
        date_from=preload_start,
        date_to=preload_end,
        cache_db_path=cache_db_path,
        use_cache=use_cache,
        offline_only=bool(args.offline_only),
        refresh_cache=bool(args.refresh_cache),
        allow_missing_cache=bool(instrument_mode == "front_nearest"),
    )
    run_eval_cache = _build_window_eval_cache(payload)

    front_selector: FrontContractSelector | None = None
    reporting_instruments = list(instruments)
    if instrument_mode == "front_nearest":
        front_selector = _build_front_selector(
            instruments=instruments,
            payload=payload,
            roll_avoid_expiry_days=front_roll_avoid_expiry_days,
        )
        reporting_instruments = list(front_selector.reporting_ids)
        if not reporting_instruments:
            raise ValueError("front_selector_empty")

    if bool(args.prefetch_only):
        return {
            "generated_at": datetime.now(tz=ZoneInfo("UTC")).isoformat(),
            "mode": "cache_prefetch_only",
            "instruments": instruments,
            "reporting_instruments": reporting_instruments,
            "instrument_mode": instrument_mode,
            "front_roll_avoid_expiry_days": int(front_roll_avoid_expiry_days),
            "cache": {
                "enabled": use_cache,
                "cache_db": (str(cache_db_path) if cache_db_path is not None else None),
                "offline_only": bool(args.offline_only),
                "refresh_cache": bool(args.refresh_cache),
                "stats": preload_stats,
            },
            "payload_sizes": {
                instrument_id: {
                    "d1": len(payload.get((instrument_id, TF.D1), [])),
                    "h1": len(payload.get((instrument_id, TF.H1), [])),
                    "m5": len(payload.get((instrument_id, TF.M5), [])),
                }
                for instrument_id in instruments
            },
        }

    base_cfg = settings.signal_engine.morning_plan.model_dump(mode="python")
    setup_cfg = base_cfg.setdefault("setups", {})
    if isinstance(setup_cfg, dict):
        current_min_target_pct = float(setup_cfg.get("min_target_return_pct", 0.0) or 0.0)
        setup_cfg["min_target_return_pct"] = max(current_min_target_pct, max(float(args.goal_min_target_return_pct), 0.0))
    costs = CostAssumptions(
        commission_ticks_per_side=float(args.commission_ticks_per_side),
        slippage_ticks_per_side=float(args.slippage_ticks_per_side),
        spread_half_ticks=float(args.spread_half_ticks),
    )
    search_algorithm = _resolve_search_algorithm(args.search_algorithm)
    tuning_profile = str(args.tuning_profile).strip()
    grid = _resolve_tuning_grid(tuning_profile)
    search_space_profile = str(args.search_space_profile).strip()
    search_space = _resolve_search_space(search_space_profile) if search_algorithm in {"RANDOM", "TPE"} else {}
    search_params = parse_search_space(search_space) if search_space else []
    hpo_trials = max(int(args.hpo_trials), 1)
    hpo_startup_trials = max(int(args.hpo_startup_trials), 1)
    hpo_seed = int(args.hpo_seed)
    cost_model_profile = _resolve_cost_model_profile(args.cost_model_profile)
    combinations = _expand_grid(grid)
    default_combo = next((item for item in combinations if item == {}), None)
    if default_combo is None:
        default_combo = combinations[0] if combinations else {}
    windows = _fold_windows(
        start_date=start_date,
        end_date=end_date,
        train_days=int(args.train_days),
        test_days=int(args.test_days),
        step_days=int(args.step_days),
    )

    folds: list[dict[str, Any]] = []
    aggregate_results: list[SetupResult] = []
    min_train_trades = max(int(args.min_train_trades), 1)
    required_instruments = min(max(int(args.min_train_instruments_with_trades), 1), len(reporting_instruments))
    min_trades_per_instrument = max(int(args.min_trades_per_instrument), 1)
    robust_mad_penalty = max(float(args.robust_mad_penalty), 0.0)
    objective = str(args.selection_objective).strip().lower()
    goal_max_trades_per_week = max(float(args.goal_max_trades_per_week), 0.0)
    goal_min_trades_per_week = max(float(args.goal_min_trades_per_week), 0.0)
    if goal_max_trades_per_week > 0.0 and goal_max_trades_per_week < goal_min_trades_per_week:
        goal_max_trades_per_week = goal_min_trades_per_week
    goal = GoalConstraints(
        min_trades_per_week=goal_min_trades_per_week,
        max_trades_per_week=goal_max_trades_per_week,
        trade_freq_penalty=max(float(args.goal_trade_freq_penalty), 0.0),
    )
    probability_gate = ProbabilityGateConfig(
        enabled=bool(args.enable_probability_gate),
        min_n_effective=max(float(args.prob_min_n_effective), 0.0),
        min_expected_return_ticks=float(args.prob_min_expected_return_ticks),
        half_life_days=max(float(args.prob_half_life_days), 1e-9),
        dirichlet_alpha=max(float(args.prob_dirichlet_alpha), 1e-9),
        context_mode=str(args.prob_context_mode),
    )
    min_prob_filled_per_fold = max(int(args.prob_min_filled_trades_per_fold), 0)
    retune_every_folds = max(int(args.retune_every_folds), 1)
    train_probability_gate = ProbabilityGateConfig(
        enabled=False,
        min_n_effective=float(probability_gate.min_n_effective),
        min_expected_return_ticks=float(probability_gate.min_expected_return_ticks),
        half_life_days=float(probability_gate.half_life_days),
        dirichlet_alpha=float(probability_gate.dirichlet_alpha),
        context_mode=str(probability_gate.context_mode),
    )
    cached_selected_params: dict[str, Any] | None = None
    for idx, window in enumerate(windows, start=1):
        train_start = window["train_start"]
        train_end = window["train_end"]
        test_start = window["test_start"]
        test_end = window["test_end"]
        fold_instrument_costs = _derive_fold_instrument_costs(
            instruments=instruments,
            payload=payload,
            tick_sizes=tick_sizes,
            train_start=train_start,
            train_end=train_end,
            base_costs=costs,
            profile=cost_model_profile,
        )
        train_scores: list[dict[str, Any]] = []
        retuned_this_fold = bool(cached_selected_params is None or ((idx - 1) % retune_every_folds == 0))
        if retuned_this_fold:
            if search_algorithm == "GRID":
                for combo in combinations:
                    train_scores.append(
                        _build_train_score_row(
                            combo=combo,
                            base_cfg=base_cfg,
                            period_start=train_start,
                            period_end=train_end,
                            instruments=instruments,
                            decision_time=decision_time,
                            tz=tz,
                            payload=payload,
                            tick_sizes=tick_sizes,
                            calendar=calendar,
                            costs=costs,
                            instrument_costs=fold_instrument_costs,
                            front_selector=front_selector,
                            eval_cache=run_eval_cache,
                            train_probability_gate=train_probability_gate,
                            min_trades_per_instrument=min_trades_per_instrument,
                            robust_mad_penalty=robust_mad_penalty,
                            selection_objective=objective,
                            goal=goal,
                        )
                    )
            else:
                rng = random.Random(int(hpo_seed) + int(idx) * 9973)
                tpe_trials: list[HpoTrialState] = []
                seen_signatures: set[str] = set()
                attempts = 0
                max_attempts = max(int(hpo_trials) * 4, int(hpo_trials))
                while len(train_scores) < int(hpo_trials) and attempts < max_attempts:
                    attempts += 1
                    if search_algorithm == "RANDOM":
                        combo = sample_random(search_params, rng)
                    else:
                        combo = sample_tpe(
                            search_params,
                            tpe_trials,
                            rng,
                            mode="max",
                            startup_trials=hpo_startup_trials,
                        )
                    signature = json.dumps(combo, sort_keys=True, ensure_ascii=True)
                    if signature in seen_signatures:
                        continue
                    seen_signatures.add(signature)
                    row = _build_train_score_row(
                        combo=combo,
                        base_cfg=base_cfg,
                        period_start=train_start,
                        period_end=train_end,
                        instruments=instruments,
                        decision_time=decision_time,
                        tz=tz,
                        payload=payload,
                        tick_sizes=tick_sizes,
                        calendar=calendar,
                        costs=costs,
                        instrument_costs=fold_instrument_costs,
                        front_selector=front_selector,
                        eval_cache=run_eval_cache,
                        train_probability_gate=train_probability_gate,
                        min_trades_per_instrument=min_trades_per_instrument,
                        robust_mad_penalty=robust_mad_penalty,
                        selection_objective=objective,
                        goal=goal,
                    )
                    eligible_trial = _is_train_row_eligible(
                        row=row,
                        min_train_trades=min_train_trades,
                        required_instruments=required_instruments,
                    )
                    tpe_objective = float(row["metrics"].get("selection_score", float("-inf")))
                    if not eligible_trial or not math.isfinite(tpe_objective):
                        tpe_objective = -1e9
                    row["metrics"]["hpo_objective"] = float(tpe_objective)
                    train_scores.append(row)
                    tpe_trials.append(HpoTrialState(params=combo, objective=float(tpe_objective)))
                if not train_scores:
                    train_scores.append(
                        _build_train_score_row(
                            combo=default_combo,
                            base_cfg=base_cfg,
                            period_start=train_start,
                            period_end=train_end,
                            instruments=instruments,
                            decision_time=decision_time,
                            tz=tz,
                            payload=payload,
                            tick_sizes=tick_sizes,
                            calendar=calendar,
                            costs=costs,
                            instrument_costs=fold_instrument_costs,
                            front_selector=front_selector,
                            eval_cache=run_eval_cache,
                            train_probability_gate=train_probability_gate,
                            min_trades_per_instrument=min_trades_per_instrument,
                            robust_mad_penalty=robust_mad_penalty,
                            selection_objective=objective,
                            goal=goal,
                        )
                    )
            eligible = [
                row
                for row in train_scores
                if _is_train_row_eligible(
                    row=row,
                    min_train_trades=min_train_trades,
                    required_instruments=required_instruments,
                )
            ]
            ranked = sorted(
                eligible,
                key=lambda row: (
                    float(row["metrics"].get("selection_score", float("-inf"))),
                    float(row["metrics"].get("robust_score", float("-inf"))),
                    float(row["summary"].get("expectancy_net_ticks", float("-inf"))),
                    float(row["summary"].get("net_ticks_sum", float("-inf"))),
                    int(row["summary"].get("filled_trades", 0)),
                ),
                reverse=True,
            )
            selected_row = ranked[0] if ranked else max(
                train_scores,
                key=lambda row: float(row["metrics"].get("selection_score", float("-inf"))),
            )
            cached_selected_params = dict(selected_row["params"])

        selected_params = dict(cached_selected_params or {})
        selected_cfg = _apply_overrides(base_cfg, selected_params)
        _, selected_train_summary, train_history = _evaluate_window(
            period_start=train_start,
            period_end=train_end,
            instruments=instruments,
            decision_time=decision_time,
            tz=tz,
            cfg=selected_cfg,
            payload=payload,
            tick_sizes=tick_sizes,
            calendar=calendar,
            costs=costs,
            instrument_costs=fold_instrument_costs,
            front_selector=front_selector,
            eval_cache=run_eval_cache,
            probability_gate=train_probability_gate,
            collect_history=True,
        )
        selected_train_metrics = asdict(
            _train_selection_metrics(
                summary=selected_train_summary,
                min_trades_per_instrument=min_trades_per_instrument,
                mad_penalty=robust_mad_penalty,
            )
        )
        if objective == "expectancy_net_ticks":
            selected_base_score = float(selected_train_summary.get("expectancy_net_ticks", 0.0))
        else:
            selected_base_score = float(selected_train_metrics.get("robust_score", float("-inf")))
        selected_train_metrics["selection_score"] = _goal_adjusted_selection_score(
            base_score=selected_base_score,
            summary=selected_train_summary,
            period_start=train_start,
            period_end=train_end,
            goal=goal,
        )
        selected_train_metrics["trades_per_week"] = _trades_per_week(
            filled_trades=int(selected_train_summary.get("filled_trades", 0) or 0),
            period_start=train_start,
            period_end=train_end,
        )
        test_rows, test_summary, _ = _evaluate_window(
            period_start=test_start,
            period_end=test_end,
            instruments=instruments,
            decision_time=decision_time,
            tz=tz,
            cfg=selected_cfg,
            payload=payload,
            tick_sizes=tick_sizes,
            calendar=calendar,
            costs=costs,
            instrument_costs=fold_instrument_costs,
            front_selector=front_selector,
            eval_cache=run_eval_cache,
            probability_gate=probability_gate,
            initial_history=train_history,
            collect_history=True,
        )
        probability_gate_fallback: dict[str, Any] = {
            "applied": False,
            "min_filled_trades_per_fold": int(min_prob_filled_per_fold),
        }
        if _should_probability_gate_fallback(
            probability_gate_enabled=bool(probability_gate.enabled),
            min_filled_trades_per_fold=min_prob_filled_per_fold,
            test_summary=test_summary,
        ):
            gated_test_summary = {
                "filled_trades": int(test_summary.get("filled_trades", 0)),
                "net_ticks_sum": float(test_summary.get("net_ticks_sum", 0.0)),
                "gated_out": int(test_summary.get("gated_out", 0)),
            }
            test_rows, test_summary, _ = _evaluate_window(
                period_start=test_start,
                period_end=test_end,
                instruments=instruments,
                decision_time=decision_time,
                tz=tz,
                cfg=selected_cfg,
                payload=payload,
                tick_sizes=tick_sizes,
                calendar=calendar,
                costs=costs,
                instrument_costs=fold_instrument_costs,
                front_selector=front_selector,
                eval_cache=run_eval_cache,
                probability_gate=None,
                initial_history=None,
                collect_history=False,
            )
            probability_gate_fallback = {
                "applied": True,
                "reason": "min_filled_trades_per_fold",
                "min_filled_trades_per_fold": int(min_prob_filled_per_fold),
                "gated_test_summary": gated_test_summary,
            }
        aggregate_results.extend(test_rows)
        fold_costs_payload = {
            instrument_id: asdict(fold_instrument_costs[instrument_id])
            for instrument_id in instruments
            if instrument_id in fold_instrument_costs
        }
        folds.append(
            {
                "fold_id": idx,
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(),
                "search_algorithm": search_algorithm,
                "retuned_this_fold": bool(retuned_this_fold),
                "train_candidates": int(len(train_scores)),
                "selected_params": selected_params,
                "train_summary": selected_train_summary,
                "train_selection_metrics": selected_train_metrics,
                "cost_assumptions_by_instrument": fold_costs_payload,
                "probability_gate_fallback": probability_gate_fallback,
                "test_summary": test_summary,
            }
        )

    overall = _summarize(aggregate_results, setups_total=sum(int(item["test_summary"]["setups_total"]) for item in folds))
    return {
        "generated_at": datetime.now(tz=ZoneInfo("UTC")).isoformat(),
        "mode": "causal_walk_forward",
        "instruments": instruments,
        "reporting_instruments": reporting_instruments,
        "instrument_mode": instrument_mode,
        "tick_sizes": tick_sizes,
        "cache": {
            "enabled": use_cache,
            "cache_db": (str(cache_db_path) if cache_db_path is not None else None),
            "offline_only": bool(args.offline_only),
            "refresh_cache": bool(args.refresh_cache),
            "stats": preload_stats,
        },
        "period": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "decision_time": decision_time.isoformat(timespec="minutes"),
            "timezone": settings.signal_engine.morning_plan.timezone,
        },
        "cost_assumptions_ticks": asdict(costs),
        "tuning_points": {
            "objective": objective,
            "search_algorithm": search_algorithm,
            "profile": tuning_profile,
            "search_space_profile": search_space_profile,
            "combinations": len(combinations),
            "hpo_trials": int(hpo_trials),
            "hpo_startup_trials": int(hpo_startup_trials),
            "hpo_seed": int(hpo_seed),
            "retune_every_folds": int(retune_every_folds),
            "cost_model_profile": cost_model_profile,
            "probability_gate": {
                "enabled": bool(probability_gate.enabled),
                "apply_on_test_only": True,
                "min_n_effective": float(probability_gate.min_n_effective),
                "min_expected_return_ticks": float(probability_gate.min_expected_return_ticks),
                "half_life_days": float(probability_gate.half_life_days),
                "dirichlet_alpha": float(probability_gate.dirichlet_alpha),
                "context_mode": str(probability_gate.context_mode),
                "min_filled_trades_per_fold": int(min_prob_filled_per_fold),
            },
            "grid": grid,
            "search_space": search_space,
            "goal": {
                "min_target_return_pct": float(args.goal_min_target_return_pct),
                "min_trades_per_week": float(goal.min_trades_per_week),
                "max_trades_per_week": float(goal.max_trades_per_week),
                "trade_freq_penalty": float(goal.trade_freq_penalty),
            },
            "effective_min_target_return_pct": float(
                base_cfg.get("setups", {}).get("min_target_return_pct", 0.0)
            ),
            "front_roll_avoid_expiry_days": int(front_roll_avoid_expiry_days),
            "min_train_trades": min_train_trades,
            "min_train_instruments_with_trades": required_instruments,
            "min_trades_per_instrument": min_trades_per_instrument,
            "robust_mad_penalty": robust_mad_penalty,
            "train_days": int(args.train_days),
            "test_days": int(args.test_days),
            "step_days": int(args.step_days),
        },
        "comparison_points": COMPARISON_POINTS,
        "folds": folds,
        "overall_test_summary": overall,
        "sample_test_results": [asdict(item) for item in aggregate_results[: min(len(aggregate_results), 50)]],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run causal walk-forward on morning-plan setups for commodity futures."
    )
    parser.add_argument("--config", type=str, default=None, help="Optional config override YAML path.")
    parser.add_argument(
        "--instrument",
        action="append",
        required=True,
        help="Instrument id (repeatable), e.g. --instrument BRH6 --instrument NGH6",
    )
    parser.add_argument(
        "--instrument-mode",
        type=str,
        default="fixed",
        choices=["fixed", "front_nearest"],
        help="fixed=trade provided contracts as-is; front_nearest=roll to nearest active contract per root.",
    )
    parser.add_argument(
        "--front-roll-avoid-expiry-days",
        type=int,
        default=3,
        help="When instrument-mode=front_nearest, avoid opening on current front within N days before its last cache date.",
    )
    parser.add_argument("--start-date", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--decision-time", type=str, default="12:00", help="HH:MM in exchange timezone.")
    parser.add_argument("--train-days", type=int, default=20)
    parser.add_argument("--test-days", type=int, default=5)
    parser.add_argument("--step-days", type=int, default=5)
    parser.add_argument(
        "--tuning-profile",
        type=str,
        default="baseline_v1",
        choices=sorted(TUNING_GRID_PROFILES.keys()),
    )
    parser.add_argument(
        "--search-algorithm",
        type=str,
        default="GRID",
        choices=["GRID", "RANDOM", "TPE"],
    )
    parser.add_argument(
        "--search-space-profile",
        type=str,
        default="intraday_goal_v1",
        choices=sorted(TUNING_SEARCH_SPACE_PROFILES.keys()),
    )
    parser.add_argument("--hpo-trials", type=int, default=24)
    parser.add_argument("--hpo-startup-trials", type=int, default=8)
    parser.add_argument("--hpo-seed", type=int, default=42)
    parser.add_argument(
        "--retune-every-folds",
        type=int,
        default=1,
        help="Re-run HPO every N folds; reuse last selected params on intermediate folds (causal speedup).",
    )
    parser.add_argument(
        "--cost-model-profile",
        type=str,
        default="fixed_v1",
        choices=list(COST_MODEL_PROFILES),
    )
    parser.add_argument("--enable-probability-gate", action="store_true")
    parser.add_argument("--prob-min-n-effective", type=float, default=50.0)
    parser.add_argument("--prob-min-expected-return-ticks", type=float, default=2.0)
    parser.add_argument("--prob-half-life-days", type=float, default=30.0)
    parser.add_argument("--prob-dirichlet-alpha", type=float, default=1.0)
    parser.add_argument("--prob-min-filled-trades-per-fold", type=int, default=0)
    parser.add_argument(
        "--prob-context-mode",
        type=str,
        default="setup_kind",
        choices=["setup_kind", "setup_group_side"],
    )
    parser.add_argument(
        "--selection-objective",
        type=str,
        default="robust_median_mad",
        choices=["robust_median_mad", "expectancy_net_ticks"],
    )
    parser.add_argument("--goal-min-target-return-pct", type=float, default=0.5)
    parser.add_argument("--goal-min-trades-per-week", type=float, default=2.0)
    parser.add_argument("--goal-max-trades-per-week", type=float, default=12.0)
    parser.add_argument("--goal-trade-freq-penalty", type=float, default=3.0)
    parser.add_argument("--min-train-trades", type=int, default=12)
    parser.add_argument("--min-train-instruments-with-trades", type=int, default=4)
    parser.add_argument("--min-trades-per-instrument", type=int, default=1)
    parser.add_argument("--robust-mad-penalty", type=float, default=0.5)
    parser.add_argument("--tick-size", action="append", default=[], help="Optional SECID=tick_size override.")
    parser.add_argument("--commission-ticks-per-side", type=float, default=0.5)
    parser.add_argument("--slippage-ticks-per-side", type=float, default=1.0)
    parser.add_argument("--spread-half-ticks", type=float, default=1.0)
    parser.add_argument(
        "--cache-db",
        type=str,
        default="data/cache/morning_plan_candles.sqlite",
        help="SQLite path for one-time candle ingest and offline reruns.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable local SQLite cache and fetch directly from ISS.",
    )
    parser.add_argument(
        "--offline-only",
        action="store_true",
        help="Disallow network fetches; fail on cache miss.",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Force refresh for requested date ranges before run.",
    )
    parser.add_argument(
        "--prefetch-only",
        action="store_true",
        help="Only load/update cache and output cache stats without walk-forward folds.",
    )
    parser.add_argument("--out-json", type=str, default=None)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    report = run_walk_forward(args)

    if str(report.get("mode")) == "cache_prefetch_only":
        cache = report.get("cache", {})
        stats = cache.get("stats", {}) if isinstance(cache, dict) else {}
        print("prefetch_only", True)
        print("cache_enabled", bool(cache.get("enabled")) if isinstance(cache, dict) else False)
        print("network_fetch_calls", int(stats.get("network_fetch_calls", 0)))
        print("network_rows", int(stats.get("network_rows", 0)))
        print("cache_rows_written", int(stats.get("cache_rows_written", 0)))
    else:
        folds = report.get("folds", [])
        overall = report.get("overall_test_summary", {})
        print("walk_forward_folds", len(folds))
        print("overall_filled_trades", int(overall.get("filled_trades", 0)))
        print("overall_fill_rate", round(float(overall.get("fill_rate", 0.0)), 4))
        print("overall_expectancy_net_ticks", round(float(overall.get("expectancy_net_ticks", 0.0)), 4))
        print("overall_net_ticks_sum", round(float(overall.get("net_ticks_sum", 0.0)), 4))

    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("report_path", str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
