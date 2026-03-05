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
from moex_carry.signal_engine.news.gate import CommodityNewsGate
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
        "setups.stop_model": ["structure", "volatility", "local_extreme", "volume_extreme"],
        "setups.stop_lookback_bars": {"type": "int", "min": 12, "max": 48, "step": 6},
        "setups.stop_volume_quantile": {"type": "float", "min": 0.60, "max": 0.90, "step": 0.05},
        "setups.require_vol_not_low": [True, False],
        "setups.entry_range_half_width_ticks": {"type": "int", "min": 0, "max": 4, "step": 1},
        "setups.entry_zone_offset_ticks": {"type": "int", "min": 0, "max": 3, "step": 1},
        "setups.entry_ttl_minutes": {"type": "int", "min": 20, "max": 180, "step": 20},
        "setups.stop_limit_fallback_to_market_min": {"type": "int", "min": 0, "max": 10, "step": 1},
        "setups.stop_limit_fallback_slip_ticks": {"type": "int", "min": 1, "max": 3, "step": 1},
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
    "intraday_goal_precision_recall_v1": {
        "execution.buffer_atr_mult": {"type": "float", "min": 0.05, "max": 0.14, "step": 0.01},
        "levels.h1.box_range_atr_mult": {"type": "float", "min": 0.8, "max": 1.8, "step": 0.1},
        "regime.d1.adx_trend_min": {"type": "int", "min": 18, "max": 26, "step": 1},
        "regime.d1.er_trend_min": {"type": "float", "min": 0.15, "max": 0.32, "step": 0.01},
        "regime.h1.dir_band_atr_mult": {"type": "float", "min": 0.12, "max": 0.28, "step": 0.01},
        "setups.max_setups_per_instrument": {"type": "int", "min": 2, "max": 6, "step": 1},
        "setups.enable_box_breakout": [True, False],
        "setups.enable_pullback_limit": [True, False],
        "setups.enable_orb_breakout": [True, False],
        "setups.enable_ema_pullback": [True, False],
        "setups.enable_vwap_pullback": [True, False],
        "setups.enable_volatility_compression_breakout": [True, False],
        "setups.orb_opening_range_minutes": {"type": "int", "min": 10, "max": 45, "step": 5},
        "setups.orb_min_range_atr_mult": {"type": "float", "min": 0.0, "max": 0.4, "step": 0.1},
        "setups.orb_max_range_atr_mult": {"type": "float", "min": 0.8, "max": 2.2, "step": 0.2},
        "setups.orb_require_price_break": [True, False],
        "setups.ema_pullback_max_dist_atr_mult": {"type": "float", "min": 0.4, "max": 1.8, "step": 0.2},
        "setups.ema_pullback_offset_ticks": {"type": "int", "min": 0, "max": 3, "step": 1},
        "setups.vwap_pullback_max_dist_atr_mult": {"type": "float", "min": 0.4, "max": 1.8, "step": 0.2},
        "setups.vwap_pullback_offset_ticks": {"type": "int", "min": 0, "max": 3, "step": 1},
        "setups.vwap_require_side_alignment": [True, False],
        "setups.vol_comp_lookback_bars": {"type": "int", "min": 8, "max": 36, "step": 4},
        "setups.vol_comp_recent_bars": {"type": "int", "min": 2, "max": 8, "step": 1},
        "setups.vol_comp_max_recent_to_prev_ratio": {"type": "float", "min": 0.25, "max": 0.90, "step": 0.05},
        "setups.vol_comp_min_range_atr_mult": {"type": "float", "min": 0.0, "max": 0.6, "step": 0.1},
        "setups.vol_comp_max_range_atr_mult": {"type": "float", "min": 0.8, "max": 2.2, "step": 0.2},
        "setups.vol_comp_require_price_break": [True, False],
        "setups.vol_comp_breakout_buffer_ticks": {"type": "int", "min": 0, "max": 3, "step": 1},
        "setups.stop_model": ["structure", "volatility", "local_extreme", "volume_extreme"],
        "setups.stop_lookback_bars": {"type": "int", "min": 12, "max": 60, "step": 6},
        "setups.stop_volume_quantile": {"type": "float", "min": 0.55, "max": 0.90, "step": 0.05},
        "setups.require_vol_not_low": [True, False],
        "setups.entry_range_half_width_ticks": {"type": "int", "min": 0, "max": 4, "step": 1},
        "setups.entry_zone_offset_ticks": {"type": "int", "min": 0, "max": 3, "step": 1},
        "setups.entry_ttl_minutes": {"type": "int", "min": 20, "max": 180, "step": 20},
        "setups.time_stop_minutes": {"type": "int", "min": 0, "max": 210, "step": 30},
        "setups.stop_limit_fallback_to_market_min": {"type": "int", "min": 0, "max": 12, "step": 1},
        "setups.stop_limit_fallback_slip_ticks": {"type": "int", "min": 1, "max": 4, "step": 1},
        "setups.rr_default": {"type": "float", "min": 0.2, "max": 1.8, "step": 0.1},
        "setups.pullback_max_dist_atr_mult": {"type": "float", "min": 0.5, "max": 1.2, "step": 0.1},
        "setups.max_risk_atr_mult": {"type": "float", "min": 0.6, "max": 1.2, "step": 0.1},
        "setups.sl_atr_mult": {"type": "float", "min": 0.4, "max": 1.0, "step": 0.1},
        "setups.min_rr_net": {"type": "float", "min": 0.0, "max": 1.1, "step": 0.1},
        "setups.min_reward_net_ticks": {"type": "float", "min": 0.0, "max": 3.0, "step": 1.0},
        "setups.min_reward_gross_ticks": {"type": "float", "min": 4.0, "max": 18.0, "step": 2.0},
        "setups.min_target_return_pct": {"type": "float", "min": 0.1, "max": 0.8, "step": 0.1},
        "setups.min_atr_h1_cost_mult": {"type": "float", "min": 2.0, "max": 7.0, "step": 1.0},
        "setups.min_atr_d1_cost_mult": {"type": "float", "min": 4.0, "max": 12.0, "step": 2.0},
    },
}

COST_MODEL_PROFILES: tuple[str, ...] = ("fixed_v1", "train_proxy_v1", "train_proxy_regime_v1")

DEFAULT_CLUSTER_ROOTS: dict[str, tuple[str, ...]] = {
    "energy": ("BR", "NG"),
    "metals": ("GD", "SV", "PL", "PT"),
}

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
class PlannedSignal:
    instrument_id: str
    trade_date: str
    as_of_ts: str
    setup_id: str
    setup_kind: str
    side: str
    entry_order_type: str
    entry_ticks: int
    entry_range_low_ticks: int
    entry_range_high_ticks: int
    sl_ticks: int
    tp_ticks: int
    horizon: str
    risk_ticks: int
    entry_expire_ts: str | None
    stop_model: str | None
    target_return_pct: float | None
    gate_status: str
    gate_reason: str | None = None
    gate_expected_return_ticks: float | None = None
    gate_n_effective: float | None = None
    gate_p_tp: float | None = None
    gate_p_sl: float | None = None
    gate_p_exit: float | None = None
    simulated_filled: bool | None = None
    simulated_outcome: str | None = None
    simulated_entry_ts: str | None = None
    simulated_exit_ts: str | None = None
    simulated_gross_ticks: float | None = None
    simulated_net_ticks: float | None = None


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
class PrecisionFilterConfig:
    enabled: bool
    min_risk_ticks: int | None
    min_target_return_pct: float | None
    allowed_sides: tuple[str, ...]
    allowed_setup_kinds: tuple[str, ...]
    allowed_stop_models: tuple[str, ...]
    allowed_decision_times: tuple[str, ...]
    dedup_setup_ids: bool


@dataclass(frozen=True)
class GoalConstraints:
    min_trades_per_week: float
    max_trades_per_week: float
    trade_freq_penalty: float
    hard_min_win_rate_net: float = 0.0
    hard_min_trades_per_week: float = 0.0
    hard_max_concentration_top_share: float = 1.0
    hard_violation_penalty: float = 1_000_000.0


@dataclass(frozen=True)
class ObjectiveScoringConfig:
    concentration_penalty_weight: float
    concentration_top_share_soft_cap: float
    normalization_floor_ticks: float
    tail_penalty_weight: float = 0.0
    tail_metric: str = "cvar"
    tail_alpha: float = 0.2
    lower_quantile: float = 0.2
    sl_rate_penalty_weight: float = 0.0
    exit_rate_penalty_weight: float = 0.0
    exit_rate_soft_cap: float = 0.35


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
    news_gates: dict[str, CommodityNewsGate]


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


def _parse_decision_times(raw_items: list[str], fallback: str) -> list[time]:
    tokens: list[str] = []
    for item in raw_items:
        for token in str(item).split(","):
            value = token.strip()
            if value:
                tokens.append(value)
    if not tokens:
        tokens = [str(fallback).strip()]
    unique = {_parse_hhmm(token) for token in tokens}
    return sorted(unique, key=lambda item: (item.hour, item.minute))


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


def _summary_concentration_top_share(summary: dict[str, Any]) -> float:
    by_instrument = summary.get("by_instrument")
    if not isinstance(by_instrument, dict) or not by_instrument:
        return 0.0
    abs_nets: list[float] = []
    for payload in by_instrument.values():
        if not isinstance(payload, dict):
            continue
        abs_nets.append(abs(float(payload.get("net_ticks_sum", 0.0))))
    total_abs = float(sum(abs_nets))
    if total_abs <= 0.0:
        return 0.0
    return float(max(abs_nets) / total_abs)


def _goal_adjusted_selection_score(
    *,
    base_score: float,
    summary: dict[str, Any],
    period_start: date,
    period_end: date,
    goal: GoalConstraints,
    extra_penalty: float = 0.0,
) -> float:
    weekly = _trades_per_week(
        filled_trades=int(summary.get("filled_trades", 0) or 0),
        period_start=period_start,
        period_end=period_end,
    )
    under = max(float(goal.min_trades_per_week) - float(weekly), 0.0)
    over = max(float(weekly) - float(goal.max_trades_per_week), 0.0)
    penalty = float(goal.trade_freq_penalty) * float(under + over)
    hard_penalty = max(float(goal.hard_violation_penalty), 0.0)
    if float(goal.hard_min_trades_per_week) > 0.0 and float(weekly) < float(goal.hard_min_trades_per_week):
        penalty += hard_penalty * (float(goal.hard_min_trades_per_week) - float(weekly))
    win_rate = float(summary.get("win_rate_net", 0.0) or 0.0)
    if float(goal.hard_min_win_rate_net) > 0.0 and float(win_rate) < float(goal.hard_min_win_rate_net):
        penalty += hard_penalty * (float(goal.hard_min_win_rate_net) - float(win_rate))
    max_top_share = min(max(float(goal.hard_max_concentration_top_share), 0.0), 1.0)
    if max_top_share < 1.0:
        top_share = _summary_concentration_top_share(summary)
        if float(top_share) > max_top_share:
            penalty += hard_penalty * (float(top_share) - max_top_share)
    penalty += max(float(extra_penalty), 0.0)
    return float(base_score - penalty)


def _negative_subfold_metrics(
    *,
    results: list[SetupResult],
    period_start: date,
    period_end: date,
    subfold_days: int,
    penalty_weight: float,
) -> dict[str, float]:
    window_days = max(int(subfold_days), 0)
    bucket_metrics = _subfold_bucket_metrics(
        results=results,
        period_start=period_start,
        period_end=period_end,
        subfold_days=window_days,
    )
    if window_days <= 0:
        return {
            "train_subfold_days": 0.0,
            "train_subfolds_with_trades": 0.0,
            "train_negative_subfolds": 0.0,
            "train_positive_subfolds": 0.0,
            "train_negative_subfold_ratio": 0.0,
            "negative_subfold_penalty": 0.0,
        }
    negative = sum(1 for item in bucket_metrics if float(item["expectancy"]) < 0.0)
    positive = sum(1 for item in bucket_metrics if float(item["expectancy"]) > 0.0)
    with_trades = len(bucket_metrics)
    ratio = float(negative / max(with_trades, 1)) if with_trades > 0 else 0.0
    penalty = max(float(penalty_weight), 0.0) * float(negative)
    return {
        "train_subfold_days": float(window_days),
        "train_subfolds_with_trades": float(with_trades),
        "train_negative_subfolds": float(negative),
        "train_positive_subfolds": float(positive),
        "train_negative_subfold_ratio": float(ratio),
        "negative_subfold_penalty": float(penalty),
    }


def _subfold_bucket_metrics(
    *,
    results: list[SetupResult],
    period_start: date,
    period_end: date,
    subfold_days: int,
) -> list[dict[str, float]]:
    window_days = max(int(subfold_days), 0)
    if window_days <= 0:
        return []
    filled_by_day: dict[date, list[SetupResult]] = {}
    for row in results:
        if not row.filled:
            continue
        try:
            day = date.fromisoformat(str(row.trade_date))
        except ValueError:
            continue
        if day < period_start or day > period_end:
            continue
        filled_by_day.setdefault(day, []).append(row)
    cursor = period_start
    buckets: list[dict[str, float]] = []
    while cursor <= period_end:
        sub_start = cursor
        sub_end = min(period_end, sub_start + timedelta(days=window_days - 1))
        cursor = sub_start + timedelta(days=window_days)
        bucket: list[SetupResult] = []
        day = sub_start
        while day <= sub_end:
            bucket.extend(filled_by_day.get(day, []))
            day = day + timedelta(days=1)
        if not bucket:
            continue
        net_sum = float(sum(item.net_ticks for item in bucket))
        expectancy = float(net_sum / float(len(bucket)))
        buckets.append(
            {
                "net_ticks_sum": float(net_sum),
                "expectancy": float(expectancy),
                "count": float(len(bucket)),
            }
        )
    return buckets


def _sample_quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(float(item) for item in values)
    clipped = min(max(float(q), 0.0), 1.0)
    pos = (len(ordered) - 1) * clipped
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return float(ordered[lower])
    weight = pos - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * weight)


def _tail_risk_metrics(
    *,
    results: list[SetupResult],
    period_start: date,
    period_end: date,
    subfold_days: int,
    tail_alpha: float,
    lower_quantile: float,
) -> dict[str, float]:
    window_days = max(int(subfold_days), 0)
    bucket_metrics = _subfold_bucket_metrics(
        results=results,
        period_start=period_start,
        period_end=period_end,
        subfold_days=window_days,
    )
    net_sums = [float(item["net_ticks_sum"]) for item in bucket_metrics]
    if not net_sums:
        return {
            "subfold_net_ticks_median": 0.0,
            "subfold_net_ticks_lower_quantile": 0.0,
            "subfold_net_ticks_cvar": 0.0,
            "subfold_negative_count": 0.0,
            "subfold_negative_share": 0.0,
            "subfold_count": 0.0,
        }
    median = float(statistics.median(net_sums))
    lower_q = _sample_quantile(net_sums, float(lower_quantile))
    alpha = min(max(float(tail_alpha), 1e-6), 1.0)
    tail_count = max(int(math.ceil(alpha * float(len(net_sums)))), 1)
    tail_values = sorted(net_sums)[:tail_count]
    cvar = float(sum(tail_values) / float(len(tail_values)))
    negative_count = sum(1 for value in net_sums if value < 0.0)
    return {
        "subfold_net_ticks_median": median,
        "subfold_net_ticks_lower_quantile": float(lower_q),
        "subfold_net_ticks_cvar": float(cvar),
        "subfold_negative_count": float(negative_count),
        "subfold_negative_share": float(negative_count / float(len(net_sums))),
        "subfold_count": float(len(net_sums)),
    }


def _normalized_selection_components(
    *,
    summary: dict[str, Any],
    min_trades_per_instrument: int,
    mad_penalty: float,
    scoring: ObjectiveScoringConfig,
) -> dict[str, float]:
    by_instrument = summary.get("by_instrument")
    if not isinstance(by_instrument, dict):
        return {
            "normalized_robust_score": float("-inf"),
            "normalized_median_expectancy": 0.0,
            "normalized_mad_expectancy": 0.0,
            "normalized_instruments": 0,
            "concentration_top_share": 0.0,
            "concentration_hhi": 0.0,
            "concentration_penalty": 0.0,
        }
    floor_ticks = max(float(scoring.normalization_floor_ticks), 1e-9)
    threshold = max(int(min_trades_per_instrument), 1)
    normalized_values: list[float] = []
    positive_nets: list[float] = []
    for row in by_instrument.values():
        if not isinstance(row, dict):
            continue
        count = int(row.get("count", 0) or 0)
        if count < threshold:
            continue
        expectancy = float(row.get("expectancy_net_ticks", 0.0))
        abs_gross_sum = abs(float(row.get("abs_gross_ticks_sum", 0.0)))
        avg_abs_gross = abs_gross_sum / float(max(count, 1))
        normalized_values.append(expectancy / max(avg_abs_gross, floor_ticks))
        positive_nets.append(max(float(row.get("net_ticks_sum", 0.0)), 0.0))
    if not normalized_values:
        return {
            "normalized_robust_score": float("-inf"),
            "normalized_median_expectancy": 0.0,
            "normalized_mad_expectancy": 0.0,
            "normalized_instruments": 0,
            "concentration_top_share": 0.0,
            "concentration_hhi": 0.0,
            "concentration_penalty": 0.0,
        }
    median_normalized = float(statistics.median(normalized_values))
    mad_normalized = float(statistics.median(abs(value - median_normalized) for value in normalized_values))
    robust_score = float(median_normalized - max(float(mad_penalty), 0.0) * mad_normalized)
    total_positive = float(sum(positive_nets))
    if total_positive > 0.0:
        shares = [value / total_positive for value in positive_nets if value > 0.0]
        top_share = float(max(shares)) if shares else 0.0
        hhi = float(sum(share * share for share in shares))
    else:
        top_share = 0.0
        hhi = 0.0
    concentration_penalty = max(top_share - float(scoring.concentration_top_share_soft_cap), 0.0)
    concentration_penalty *= max(float(scoring.concentration_penalty_weight), 0.0)
    return {
        "normalized_robust_score": robust_score,
        "normalized_median_expectancy": median_normalized,
        "normalized_mad_expectancy": mad_normalized,
        "normalized_instruments": int(len(normalized_values)),
        "concentration_top_share": top_share,
        "concentration_hhi": hhi,
        "concentration_penalty": float(concentration_penalty),
    }


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
    range_samples = list(med_range_ticks_by_instrument.values())
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

        range_rank = _value_rank(float(med_range_ticks), range_samples)
        slippage = float(base_costs.slippage_ticks_per_side)
        if med_range_ticks >= 30.0:
            slippage += 0.5
        elif med_range_ticks >= 15.0:
            slippage += 0.25
        if volume_rank <= 0.33:
            slippage += 0.25
        if profile == "train_proxy_regime_v1":
            if range_rank >= 0.80:
                spread_half += 0.25
                slippage += 0.35
            elif range_rank >= 0.60:
                slippage += 0.20
            if volume_rank <= 0.20:
                spread_half += 0.25
                slippage += 0.20
        slippage = min(max(slippage, 0.5), 3.0)
        spread_half = min(max(float(spread_half), 0.5), 3.0)
        result[instrument_id] = CostAssumptions(
            commission_ticks_per_side=float(base_costs.commission_ticks_per_side),
            slippage_ticks_per_side=float(slippage),
            spread_half_ticks=float(spread_half),
        )
    return result


def _apply_cost_stress(costs: CostAssumptions, stress_mult: float) -> CostAssumptions:
    mult = max(float(stress_mult), 1e-9)
    if abs(mult - 1.0) <= 1e-12:
        return costs
    return CostAssumptions(
        commission_ticks_per_side=float(costs.commission_ticks_per_side) * mult,
        slippage_ticks_per_side=float(costs.slippage_ticks_per_side) * mult,
        spread_half_ticks=float(costs.spread_half_ticks) * mult,
    )


def _apply_overrides(base_cfg: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
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


def _split_cluster_overrides(overrides: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    global_overrides: dict[str, Any] = {}
    cluster_overrides: dict[str, dict[str, Any]] = {}
    for dotted_path, value in overrides.items():
        parts = str(dotted_path).split(".")
        if len(parts) >= 3 and str(parts[0]).lower() == "cluster":
            cluster_name = str(parts[1]).strip().lower()
            if cluster_name:
                cluster_overrides.setdefault(cluster_name, {})[".".join(parts[2:])] = value
                continue
        global_overrides[str(dotted_path)] = value
    return global_overrides, cluster_overrides


def _parse_cluster_roots(items: list[str]) -> dict[str, str]:
    root_to_cluster: dict[str, str] = {}
    seen_cluster = False
    tokens: list[str] = []
    for item in items:
        for token in str(item).split(";"):
            normalized = str(token).strip()
            if normalized:
                tokens.append(normalized)
    for item in tokens:
        if "=" not in item:
            raise ValueError(f"invalid_cluster_pair:{item}")
        cluster, roots_csv = item.split("=", 1)
        cluster_name = str(cluster).strip().lower()
        if not cluster_name:
            raise ValueError(f"invalid_cluster_pair:{item}")
        roots = [value.strip().upper() for value in str(roots_csv).split(",") if str(value).strip()]
        if not roots:
            raise ValueError(f"invalid_cluster_pair:{item}")
        for root in roots:
            root_to_cluster[root] = cluster_name
        seen_cluster = True
    if seen_cluster:
        return root_to_cluster
    for cluster_name, roots in DEFAULT_CLUSTER_ROOTS.items():
        for root in roots:
            root_to_cluster[str(root).upper()] = str(cluster_name).lower()
    return root_to_cluster


def _cluster_for_instrument(
    *,
    instrument_id: str,
    root_to_cluster: dict[str, str] | None,
) -> str | None:
    if not root_to_cluster:
        return None
    root = _instrument_group(instrument_id)
    cluster = root_to_cluster.get(root)
    if cluster is not None:
        return str(cluster)
    return None


def _cfg_for_instrument(
    *,
    base_cfg: dict[str, Any],
    instrument_id: str,
    cluster_overrides: dict[str, dict[str, Any]] | None,
    root_to_cluster: dict[str, str] | None,
    cfg_cache: dict[tuple[str, str], dict[str, Any]],
) -> tuple[dict[str, Any], str | None]:
    cluster_name = _cluster_for_instrument(instrument_id=instrument_id, root_to_cluster=root_to_cluster)
    key = (str(instrument_id), str(cluster_name or ""))
    cached = cfg_cache.get(key)
    if cached is not None:
        return cached, cluster_name
    cfg = base_cfg
    if cluster_name and cluster_overrides and cluster_name in cluster_overrides:
        cfg = _apply_overrides(cfg, cluster_overrides[cluster_name])
    cfg_cache[key] = cfg
    return cfg, cluster_name


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


def _setup_stop_model(setup: Setup) -> str | None:
    raw_stop_model = setup.sl_order.meta.get("stop_model") or setup.entry_order.meta.get("stop_model")
    return str(raw_stop_model) if raw_stop_model is not None else None


def _setup_target_return_pct(setup: Setup) -> float | None:
    raw_target_return_pct = setup.entry_order.meta.get("target_return_pct")
    try:
        if raw_target_return_pct is not None:
            return float(raw_target_return_pct)
    except (TypeError, ValueError):
        return None
    return None


def _entry_range_ticks(setup: Setup) -> tuple[int, int]:
    entry = int(setup.entry_order.price_ticks)
    candidates: list[int] = [entry]
    for value in (
        setup.entry_order.price_range_low_ticks,
        setup.entry_order.price_range_high_ticks,
        setup.entry_order.meta.get("entry_range_low_ticks"),
        setup.entry_order.meta.get("entry_range_high_ticks"),
    ):
        try:
            if value is not None:
                candidates.append(int(value))
        except (TypeError, ValueError):
            continue
    return int(min(candidates)), int(max(candidates))


def _build_planned_signal(
    *,
    instrument_id: str,
    as_of_ts: datetime,
    setup: Setup,
    gate_status: str,
    gate_reason: str | None = None,
    gate_expected_return_ticks: float | None = None,
    gate_n_effective: float | None = None,
    gate_p_tp: float | None = None,
    gate_p_sl: float | None = None,
    gate_p_exit: float | None = None,
    simulated: SetupResult | None = None,
) -> PlannedSignal:
    range_low, range_high = _entry_range_ticks(setup)
    target_return_pct = _setup_target_return_pct(setup)
    stop_model = _setup_stop_model(setup)
    return PlannedSignal(
        instrument_id=str(instrument_id),
        trade_date=as_of_ts.date().isoformat(),
        as_of_ts=as_of_ts.isoformat(),
        setup_id=str(setup.setup_id),
        setup_kind=_setup_kind(setup),
        side=setup.side.value,
        entry_order_type=_order_type_name(setup),
        entry_ticks=int(setup.entry_order.price_ticks),
        entry_range_low_ticks=int(range_low),
        entry_range_high_ticks=int(range_high),
        sl_ticks=int(setup.sl_order.price_ticks),
        tp_ticks=int(setup.tp_order.price_ticks),
        horizon=str(setup.horizon),
        risk_ticks=int(setup.risk_ticks),
        entry_expire_ts=setup.entry_order.expire_ts.isoformat() if setup.entry_order.expire_ts else None,
        stop_model=stop_model,
        target_return_pct=target_return_pct,
        gate_status=str(gate_status),
        gate_reason=gate_reason,
        gate_expected_return_ticks=gate_expected_return_ticks,
        gate_n_effective=gate_n_effective,
        gate_p_tp=gate_p_tp,
        gate_p_sl=gate_p_sl,
        gate_p_exit=gate_p_exit,
        simulated_filled=(bool(simulated.filled) if simulated is not None else None),
        simulated_outcome=(str(simulated.outcome) if simulated is not None else None),
        simulated_entry_ts=(str(simulated.entry_ts) if simulated is not None else None),
        simulated_exit_ts=(str(simulated.exit_ts) if simulated is not None else None),
        simulated_gross_ticks=(float(simulated.gross_ticks) if simulated is not None else None),
        simulated_net_ticks=(float(simulated.net_ticks) if simulated is not None else None),
    )


def _precision_filter_reason(
    *,
    setup: Setup,
    as_of_ts: datetime,
    precision_filter: PrecisionFilterConfig,
) -> str | None:
    if not bool(precision_filter.enabled):
        return None
    if precision_filter.allowed_decision_times:
        decision_time = as_of_ts.time().isoformat(timespec="minutes")
        if decision_time not in set(precision_filter.allowed_decision_times):
            return "precision_decision_time"
    side = setup.side.value.upper()
    if precision_filter.allowed_sides and side not in set(precision_filter.allowed_sides):
        return "precision_side"
    setup_kind = _setup_kind(setup).upper()
    if precision_filter.allowed_setup_kinds and setup_kind not in set(precision_filter.allowed_setup_kinds):
        return "precision_setup_kind"
    stop_model = (_setup_stop_model(setup) or "").strip().lower()
    if precision_filter.allowed_stop_models and stop_model not in set(precision_filter.allowed_stop_models):
        return "precision_stop_model"
    if precision_filter.min_risk_ticks is not None and int(setup.risk_ticks) < int(precision_filter.min_risk_ticks):
        return "precision_min_risk_ticks"
    if precision_filter.min_target_return_pct is not None:
        target_return_pct = _setup_target_return_pct(setup)
        if target_return_pct is None or float(target_return_pct) < float(precision_filter.min_target_return_pct):
            return "precision_min_target_return_pct"
    return None


def _entry_fill(
    *,
    setup: Setup,
    bars: list[Candle],
    tick_size: float,
) -> tuple[datetime, int] | None:
    side = setup.side
    entry_ticks = int(setup.entry_order.price_ticks)
    entry_range_low, entry_range_high = _entry_range_ticks(setup)
    order_type = _order_type_name(setup)

    if order_type == "LIMIT":
        for bar in bars:
            high_ticks = price_to_ticks(float(bar.high), tick_size)
            low_ticks = price_to_ticks(float(bar.low), tick_size)
            if side == Side.BUY and low_ticks <= entry_range_high:
                # Conservative fill inside range for BUY: worse (higher) price.
                return bar.ts, int(entry_range_high)
            if side == Side.SELL and high_ticks >= entry_range_low:
                # Conservative fill inside range for SELL: worse (lower) price.
                return bar.ts, int(entry_range_low)
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
        raw_fallback_min = setup.entry_order.meta.get("stop_limit_fallback_to_market_min")
        raw_fallback_slip = setup.entry_order.meta.get("stop_limit_fallback_slip_ticks")
        try:
            fallback_minutes = max(int(raw_fallback_min), 0) if raw_fallback_min is not None else 0
        except (TypeError, ValueError):
            fallback_minutes = 0
        try:
            fallback_slip_ticks = max(int(raw_fallback_slip), 0) if raw_fallback_slip is not None else 0
        except (TypeError, ValueError):
            fallback_slip_ticks = 0
        triggered = False
        trigger_ts: datetime | None = None
        for bar in bars:
            high_ticks = price_to_ticks(float(bar.high), tick_size)
            low_ticks = price_to_ticks(float(bar.low), tick_size)
            if not triggered:
                if side == Side.BUY and high_ticks >= entry_ticks:
                    triggered = True
                    trigger_ts = bar.ts
                if side == Side.SELL and low_ticks <= entry_ticks:
                    triggered = True
                    trigger_ts = bar.ts
            if not triggered:
                continue
            if side == Side.BUY and low_ticks <= limit_ticks:
                return bar.ts, int(limit_ticks)
            if side == Side.SELL and high_ticks >= limit_ticks:
                return bar.ts, int(limit_ticks)
            if fallback_minutes > 0 and trigger_ts is not None:
                elapsed_min = (bar.ts - trigger_ts).total_seconds() / 60.0
                if elapsed_min >= float(fallback_minutes):
                    fallback_fill = (
                        int(entry_ticks + fallback_slip_ticks)
                        if side == Side.BUY
                        else int(entry_ticks - fallback_slip_ticks)
                    )
                    return bar.ts, int(fallback_fill)
        return None

    return None


def _exit_result(
    *,
    setup: Setup,
    bars: list[Candle],
    tick_size: float,
    fill_ts: datetime,
    fill_ticks: int,
    time_stop_deadline: datetime | None = None,
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
        if time_stop_deadline is not None and bar.ts >= time_stop_deadline:
            return "EXIT", bar.ts, price_to_ticks(float(bar.close), tick_size)
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
    raw_time_stop_minutes = setup.entry_order.meta.get("time_stop_minutes")
    try:
        time_stop_minutes = max(int(raw_time_stop_minutes), 0) if raw_time_stop_minutes is not None else 0
    except (TypeError, ValueError):
        time_stop_minutes = 0
    time_stop_deadline = (
        fill_ts + timedelta(minutes=int(time_stop_minutes))
        if int(time_stop_minutes) > 0
        else None
    )
    exit_bars = [bar for bar in m5_rows if fill_ts < bar.ts <= horizon_deadline]
    outcome, exit_ts, exit_ticks = _exit_result(
        setup=setup,
        bars=exit_bars,
        tick_size=tick_size,
        fill_ts=fill_ts,
        fill_ticks=fill_ticks,
        time_stop_deadline=time_stop_deadline,
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
        slot = by_kind.setdefault(
            row.setup_kind,
            {
                "count": 0.0,
                "net_ticks_sum": 0.0,
                "win_count": 0.0,
                "tp_count": 0.0,
                "sl_count": 0.0,
                "exit_count": 0.0,
            },
        )
        slot["count"] += 1.0
        slot["net_ticks_sum"] += float(row.net_ticks)
        if row.net_ticks > 0.0:
            slot["win_count"] += 1.0
        if row.outcome == "TP":
            slot["tp_count"] += 1.0
        elif row.outcome == "SL":
            slot["sl_count"] += 1.0
        elif row.outcome == "EXIT":
            slot["exit_count"] += 1.0
        inst_slot = by_instrument.setdefault(
            row.instrument_id,
            {
                "count": 0.0,
                "net_ticks_sum": 0.0,
                "gross_ticks_sum": 0.0,
                "abs_gross_ticks_sum": 0.0,
                "tp_count": 0.0,
                "sl_count": 0.0,
                "exit_count": 0.0,
                "win_count": 0.0,
            },
        )
        inst_slot["count"] += 1.0
        inst_slot["net_ticks_sum"] += float(row.net_ticks)
        inst_slot["gross_ticks_sum"] += float(row.gross_ticks)
        inst_slot["abs_gross_ticks_sum"] += abs(float(row.gross_ticks))
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
        slot["win_rate_net"] = float(slot["win_count"] / count) if count > 0 else 0.0
        slot["tp_rate"] = float(slot["tp_count"] / count) if count > 0 else 0.0
        slot["sl_rate"] = float(slot["sl_count"] / count) if count > 0 else 0.0
        slot["exit_rate"] = float(slot["exit_count"] / count) if count > 0 else 0.0
        slot["count"] = int(count)
        slot["win_count"] = int(slot["win_count"])
        slot["tp_count"] = int(slot["tp_count"])
        slot["sl_count"] = int(slot["sl_count"])
        slot["exit_count"] = int(slot["exit_count"])
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
        "abs_gross_ticks_sum": float(sum(abs(row.gross_ticks) for row in filled)),
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
        news_gates={},
    )


def _append_generator_rejection_trace(
    *,
    as_of_ts: datetime,
    instrument_id: str,
    trace_rows: list[dict[str, Any]],
    counts: dict[str, int] | None,
    sample: list[dict[str, Any]] | None,
    sample_limit: int,
) -> None:
    sample_cap = max(int(sample_limit), 0)
    for item in trace_rows:
        if not isinstance(item, dict):
            continue
        setup_kind = str(item.get("setup_kind", "UNKNOWN")).strip().upper() or "UNKNOWN"
        rule = str(item.get("rule", "unspecified")).strip().lower() or "unspecified"
        key = f"{setup_kind}:{rule}"
        if counts is not None:
            counts[key] = int(counts.get(key, 0)) + 1
        if sample is not None and (sample_cap <= 0 or len(sample) < sample_cap):
            payload: dict[str, Any] = {
                "instrument_id": str(instrument_id),
                "as_of_ts": as_of_ts.isoformat(),
                "setup_kind": setup_kind,
                "rule": rule,
            }
            details = item.get("details")
            if isinstance(details, dict) and details:
                payload["details"] = details
            sample.append(payload)


def _compute_setups_cached(
    *,
    eval_cache: WindowEvalCache,
    cfg: dict[str, Any],
    calendar: MarketCalendar,
    as_of_ts: datetime,
    instrument_id: str,
    tick_size: float,
    collect_generator_rejection_trace: bool = False,
    generator_rejection_trace_counts: dict[str, int] | None = None,
    generator_rejection_trace_sample: list[dict[str, Any]] | None = None,
    generator_rejection_trace_sample_limit: int = 0,
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
    if bool(collect_generator_rejection_trace) and hasattr(setup_generator, "consume_rejection_trace"):
        trace_rows = setup_generator.consume_rejection_trace()
        if trace_rows:
            _append_generator_rejection_trace(
                as_of_ts=as_of_ts,
                instrument_id=instrument_id,
                trace_rows=trace_rows,
                counts=generator_rejection_trace_counts,
                sample=generator_rejection_trace_sample,
                sample_limit=generator_rejection_trace_sample_limit,
            )
    news_cfg = _cfg_section(cfg, "news_gate")
    news_sig = _stable_signature(news_cfg)
    news_gate = eval_cache.news_gates.get(news_sig)
    if news_gate is None:
        news_gate = CommodityNewsGate(news_cfg)
        eval_cache.news_gates[news_sig] = news_gate
    decision = news_gate.evaluate(as_of_ts=as_of_ts, instrument_id=instrument_id)
    if decision.action == "block":
        return []
    if decision.action == "reduce" and setups:
        setups = news_gate.reduce_setups_by_risk(setups, news_gate.reduce_max_setups)
    return setups


def _build_train_score_row(
    *,
    combo: dict[str, Any],
    base_cfg: dict[str, Any],
    period_start: date,
    period_end: date,
    instruments: list[str],
    decision_times: list[time],
    tz: ZoneInfo,
    payload: dict[tuple[str, TF], list[Candle]],
    tick_sizes: dict[str, float],
    calendar: MarketCalendar,
    costs: CostAssumptions,
    instrument_costs: dict[str, CostAssumptions] | None,
    front_selector: FrontContractSelector | None,
    eval_cache: WindowEvalCache | None,
    train_probability_gate: ProbabilityGateConfig,
    cluster_root_map: dict[str, str] | None,
    min_trades_per_instrument: int,
    robust_mad_penalty: float,
    selection_objective: str,
    goal: GoalConstraints,
    objective_scoring: ObjectiveScoringConfig,
    objective_negative_fold_penalty: float,
    objective_subfold_days: int,
    precision_filter: PrecisionFilterConfig,
) -> dict[str, Any]:
    global_overrides, cluster_overrides = _split_cluster_overrides(combo)
    cfg = _apply_overrides(base_cfg, global_overrides)
    train_rows, train_summary, _, _ = _evaluate_window(
        period_start=period_start,
        period_end=period_end,
        instruments=instruments,
        decision_times=decision_times,
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
        cluster_overrides=cluster_overrides,
        cluster_root_map=cluster_root_map,
        collect_history=False,
        precision_filter=precision_filter,
    )
    metrics = asdict(
        _train_selection_metrics(
            summary=train_summary,
            min_trades_per_instrument=min_trades_per_instrument,
            mad_penalty=robust_mad_penalty,
        )
    )
    normalized_metrics = _normalized_selection_components(
        summary=train_summary,
        min_trades_per_instrument=min_trades_per_instrument,
        mad_penalty=robust_mad_penalty,
        scoring=objective_scoring,
    )
    metrics.update(normalized_metrics)
    negative_fold_metrics = _negative_subfold_metrics(
        results=train_rows,
        period_start=period_start,
        period_end=period_end,
        subfold_days=objective_subfold_days,
        penalty_weight=objective_negative_fold_penalty,
    )
    metrics.update(negative_fold_metrics)
    tail_metrics = _tail_risk_metrics(
        results=train_rows,
        period_start=period_start,
        period_end=period_end,
        subfold_days=objective_subfold_days,
        tail_alpha=float(objective_scoring.tail_alpha),
        lower_quantile=float(objective_scoring.lower_quantile),
    )
    metrics.update(tail_metrics)
    concentration_penalty = 0.0
    negative_subfold_penalty = float(negative_fold_metrics.get("negative_subfold_penalty", 0.0))
    tail_reference = (
        float(tail_metrics.get("subfold_net_ticks_cvar", 0.0))
        if str(objective_scoring.tail_metric).strip().lower() == "cvar"
        else float(tail_metrics.get("subfold_net_ticks_lower_quantile", 0.0))
    )
    tail_penalty = max(-tail_reference, 0.0) * max(float(objective_scoring.tail_penalty_weight), 0.0)
    sl_rate = float(train_summary.get("sl_rate", 0.0))
    exit_rate = float(train_summary.get("exit_rate", 0.0))
    sl_penalty = sl_rate * max(float(objective_scoring.sl_rate_penalty_weight), 0.0)
    exit_penalty = max(exit_rate - float(objective_scoring.exit_rate_soft_cap), 0.0)
    exit_penalty *= max(float(objective_scoring.exit_rate_penalty_weight), 0.0)
    kpi_penalty = float(sl_penalty + exit_penalty)
    metrics["tail_penalty"] = float(tail_penalty)
    metrics["sl_rate_penalty"] = float(sl_penalty)
    metrics["exit_rate_penalty"] = float(exit_penalty)
    metrics["kpi_penalty"] = float(kpi_penalty)
    if selection_objective == "expectancy_net_ticks":
        base_score = float(train_summary.get("expectancy_net_ticks", 0.0))
    elif selection_objective == "robust_normalized":
        base_score = float(normalized_metrics.get("normalized_robust_score", float("-inf")))
        concentration_penalty = float(normalized_metrics.get("concentration_penalty", 0.0))
    else:
        base_score = float(metrics.get("robust_score", float("-inf")))
    selection_score = _goal_adjusted_selection_score(
        base_score=base_score,
        summary=train_summary,
        period_start=period_start,
        period_end=period_end,
        goal=goal,
        extra_penalty=concentration_penalty + negative_subfold_penalty + tail_penalty + kpi_penalty,
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
    decision_times: list[time],
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
    cluster_overrides: dict[str, dict[str, Any]] | None = None,
    cluster_root_map: dict[str, str] | None = None,
    initial_history: list[ProbHistoryEvent] | None = None,
    collect_history: bool = False,
    precision_filter: PrecisionFilterConfig | None = None,
    collect_generator_rejection_trace: bool = False,
    generator_rejection_trace_sample_limit: int = 80,
) -> tuple[list[SetupResult], dict[str, Any], list[ProbHistoryEvent], list[PlannedSignal]]:
    builders: dict[tuple[str, str], MorningPlanBuilder] = {}
    if eval_cache is None:
        provider = InMemoryCandleProvider(payload)
    cfg_cache: dict[tuple[str, str], dict[str, Any]] = {}
    rows: list[SetupResult] = []
    planned_rows: list[PlannedSignal] = []
    setups_total = 0
    history: list[ProbHistoryEvent] = list(initial_history or [])
    generator_rejection_counts: dict[str, int] = {}
    generator_rejection_sample: list[dict[str, Any]] = []
    gate_mode = str(probability_gate.context_mode) if probability_gate is not None else "setup_kind"
    precision = precision_filter or PrecisionFilterConfig(
        enabled=False,
        min_risk_ticks=None,
        min_target_return_pct=None,
        allowed_sides=(),
        allowed_setup_kinds=(),
        allowed_stop_models=(),
        allowed_decision_times=(),
        dedup_setup_ids=False,
    )
    seen_setup_ids: set[str] = set()
    for day in _iter_days(period_start, period_end):
        day_targets = (
            front_selector.resolve_day(day)
            if front_selector is not None
            else [(instrument_id, instrument_id) for instrument_id in instruments]
        )
        for decision_time in decision_times:
            as_of_ts = datetime.combine(day, decision_time, tzinfo=tz)
            if not calendar.is_trading_time(as_of_ts):
                continue
            for report_instrument_id, secid in day_targets:
                effective_cfg, _ = _cfg_for_instrument(
                    base_cfg=cfg,
                    instrument_id=secid,
                    cluster_overrides=cluster_overrides,
                    root_to_cluster=cluster_root_map,
                    cfg_cache=cfg_cache,
                )
                tick_size = float(tick_sizes[secid])
                effective_costs = costs if instrument_costs is None else instrument_costs.get(secid, costs)
                if eval_cache is None:
                    cfg_sig = _stable_signature(effective_cfg)
                    builder_key = (secid, cfg_sig)
                    builder = builders.get(builder_key)
                    if builder is None:
                        builder = MorningPlanBuilder(provider, calendar, effective_cfg)
                        builders[builder_key] = builder
                    plan = builder.build_plan(as_of_ts=as_of_ts, instrument_id=secid, tick_size=tick_size)
                    setups = plan.setups
                else:
                    setups = _compute_setups_cached(
                        eval_cache=eval_cache,
                        cfg=effective_cfg,
                        calendar=calendar,
                        as_of_ts=as_of_ts,
                        instrument_id=secid,
                        tick_size=tick_size,
                        collect_generator_rejection_trace=collect_generator_rejection_trace,
                        generator_rejection_trace_counts=generator_rejection_counts,
                        generator_rejection_trace_sample=generator_rejection_sample,
                        generator_rejection_trace_sample_limit=generator_rejection_trace_sample_limit,
                    )
                m5_rows = payload.get((secid, TF.M5), [])
                setups_total += len(setups)
                for setup in setups:
                    if bool(precision.enabled):
                        setup_id = str(setup.setup_id)
                        if bool(precision.dedup_setup_ids):
                            if setup_id in seen_setup_ids:
                                reason = "precision_duplicate_setup_id"
                                planned_rows.append(
                                    _build_planned_signal(
                                        instrument_id=report_instrument_id,
                                        as_of_ts=as_of_ts,
                                        setup=setup,
                                        gate_status="BLOCK",
                                        gate_reason=reason,
                                        gate_expected_return_ticks=0.0,
                                        gate_n_effective=0.0,
                                        gate_p_tp=0.0,
                                        gate_p_sl=0.0,
                                        gate_p_exit=0.0,
                                    )
                                )
                                rows.append(
                                    _gated_out_result(
                                        instrument_id=report_instrument_id,
                                        as_of_ts=as_of_ts,
                                        setup=setup,
                                        reason=reason,
                                        expected_return_ticks=0.0,
                                        forecast={"n_effective": 0.0, "p_tp": 0.0, "p_sl": 0.0, "p_exit": 0.0},
                                    )
                                )
                                continue
                            seen_setup_ids.add(setup_id)
                        precision_reason = _precision_filter_reason(
                            setup=setup,
                            as_of_ts=as_of_ts,
                            precision_filter=precision,
                        )
                        if precision_reason is not None:
                            planned_rows.append(
                                _build_planned_signal(
                                    instrument_id=report_instrument_id,
                                    as_of_ts=as_of_ts,
                                    setup=setup,
                                    gate_status="BLOCK",
                                    gate_reason=precision_reason,
                                    gate_expected_return_ticks=0.0,
                                    gate_n_effective=0.0,
                                    gate_p_tp=0.0,
                                    gate_p_sl=0.0,
                                    gate_p_exit=0.0,
                                )
                            )
                            rows.append(
                                _gated_out_result(
                                    instrument_id=report_instrument_id,
                                    as_of_ts=as_of_ts,
                                    setup=setup,
                                    reason=precision_reason,
                                    expected_return_ticks=0.0,
                                    forecast={"n_effective": 0.0, "p_tp": 0.0, "p_sl": 0.0, "p_exit": 0.0},
                                )
                            )
                            continue
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
                            planned_rows.append(
                                _build_planned_signal(
                                    instrument_id=report_instrument_id,
                                    as_of_ts=as_of_ts,
                                    setup=setup,
                                    gate_status="BLOCK",
                                    gate_reason="low_n_effective",
                                    gate_expected_return_ticks=float(expected_value),
                                    gate_n_effective=float(forecast.get("n_effective", 0.0)),
                                    gate_p_tp=float(forecast.get("p_tp", 0.0)),
                                    gate_p_sl=float(forecast.get("p_sl", 0.0)),
                                    gate_p_exit=float(forecast.get("p_exit", 0.0)),
                                )
                            )
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
                            planned_rows.append(
                                _build_planned_signal(
                                    instrument_id=report_instrument_id,
                                    as_of_ts=as_of_ts,
                                    setup=setup,
                                    gate_status="BLOCK",
                                    gate_reason="expected_return_below_threshold",
                                    gate_expected_return_ticks=float(expected_value),
                                    gate_n_effective=float(forecast.get("n_effective", 0.0)),
                                    gate_p_tp=float(forecast.get("p_tp", 0.0)),
                                    gate_p_sl=float(forecast.get("p_sl", 0.0)),
                                    gate_p_exit=float(forecast.get("p_exit", 0.0)),
                                )
                            )
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
                    simulated = _simulate_setup(
                        instrument_id=report_instrument_id,
                        as_of_ts=as_of_ts,
                        setup=setup,
                        m5_rows=m5_rows,
                        tick_size=tick_size,
                        calendar=calendar,
                        costs=effective_costs,
                    )
                    rows.append(simulated)
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
                        planned_rows.append(
                            _build_planned_signal(
                                instrument_id=report_instrument_id,
                                as_of_ts=as_of_ts,
                                setup=setup,
                                gate_status="ALLOW",
                                gate_reason=None,
                                gate_expected_return_ticks=float(expected_value),
                                gate_n_effective=float(forecast.get("n_effective", 0.0)),
                                gate_p_tp=float(forecast.get("p_tp", 0.0)),
                                gate_p_sl=float(forecast.get("p_sl", 0.0)),
                                gate_p_exit=float(forecast.get("p_exit", 0.0)),
                                simulated=simulated,
                            )
                        )
                    else:
                        planned_rows.append(
                            _build_planned_signal(
                                instrument_id=report_instrument_id,
                                as_of_ts=as_of_ts,
                                setup=setup,
                                gate_status="DISABLED",
                                simulated=simulated,
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
    if bool(collect_generator_rejection_trace):
        sorted_counts = dict(
            sorted(
                generator_rejection_counts.items(),
                key=lambda item: (-int(item[1]), str(item[0])),
            )
        )
        summary["generator_rejection_trace"] = {
            "total": int(sum(generator_rejection_counts.values())),
            "counts": sorted_counts,
            "sample": list(generator_rejection_sample),
        }
    return rows, summary, history, planned_rows


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


def _parse_csv_tokens(items: list[str]) -> list[str]:
    tokens: list[str] = []
    for item in items:
        for part in str(item).split(","):
            value = str(part).strip()
            if value:
                tokens.append(value)
    return tokens


def _parse_news_commodity_map(items: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in _parse_csv_tokens(items):
        if "=" not in item:
            raise ValueError(f"invalid_news_commodity_map_pair:{item}")
        root, commodity = item.split("=", 1)
        normalized_root = str(root).strip().upper()
        normalized_commodity = str(commodity).strip().upper()
        if not normalized_root or not normalized_commodity:
            raise ValueError(f"invalid_news_commodity_map_pair:{item}")
        parsed[normalized_root] = normalized_commodity
    return parsed


def _fold_windows(
    *,
    start_date: date,
    end_date: date,
    train_days: int,
    test_days: int,
    step_days: int,
    embargo_days: int = 0,
    purge_days: int = 0,
) -> list[dict[str, date]]:
    windows: list[dict[str, date]] = []
    embargo = max(int(embargo_days), 0)
    purge = max(int(purge_days), 0)
    cursor = start_date
    while cursor <= end_date:
        test_start = cursor
        test_end = min(end_date, test_start + timedelta(days=max(test_days, 1) - 1))
        train_end = test_start - timedelta(days=embargo + 1)
        train_start = train_end - timedelta(days=max(train_days, 1) - 1)
        windows.append(
            {
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
            }
        )
        next_cursor = cursor + timedelta(days=max(step_days, 1))
        min_cursor = test_end + timedelta(days=purge + 1)
        cursor = max(next_cursor, min_cursor)
    return windows


def _acceptance_summary(
    *,
    folds: list[dict[str, Any]],
    tail_alpha: float,
    max_negative_fold_share: float,
    min_median_fold_net_ticks: float,
    min_tail_cvar_ticks: float,
    holdout_summary: dict[str, Any] | None,
    overall_summary: dict[str, Any] | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    goal: GoalConstraints | None = None,
) -> dict[str, Any]:
    net_by_fold = [
        float((row.get("test_summary") or {}).get("net_ticks_sum", 0.0))
        for row in folds
    ]
    if net_by_fold:
        negative_count = sum(1 for value in net_by_fold if value < 0.0)
        negative_share = float(negative_count / float(len(net_by_fold)))
        median_net = float(statistics.median(net_by_fold))
        alpha = min(max(float(tail_alpha), 1e-6), 1.0)
        tail_count = max(int(math.ceil(alpha * float(len(net_by_fold)))), 1)
        tail_values = sorted(net_by_fold)[:tail_count]
        tail_cvar = float(sum(tail_values) / float(len(tail_values)))
    else:
        negative_count = 0
        negative_share = 1.0
        median_net = 0.0
        tail_cvar = 0.0
    reasons: list[str] = []
    if negative_share > float(max_negative_fold_share):
        reasons.append("negative_fold_share")
    if median_net < float(min_median_fold_net_ticks):
        reasons.append("median_fold_net_ticks")
    if tail_cvar < float(min_tail_cvar_ticks):
        reasons.append("tail_cvar")
    if holdout_summary is not None and float(holdout_summary.get("net_ticks_sum", 0.0)) <= 0.0:
        reasons.append("holdout_net_ticks_non_positive")
    overall_win_rate = 0.0
    overall_tpw = 0.0
    overall_top_share = 0.0
    if overall_summary is not None:
        overall_win_rate = float(overall_summary.get("win_rate_net", 0.0) or 0.0)
        overall_top_share = _summary_concentration_top_share(overall_summary)
        if period_start is not None and period_end is not None:
            overall_tpw = _trades_per_week(
                filled_trades=int(overall_summary.get("filled_trades", 0) or 0),
                period_start=period_start,
                period_end=period_end,
            )
    if goal is not None:
        if float(goal.hard_min_win_rate_net) > 0.0 and float(overall_win_rate) < float(goal.hard_min_win_rate_net):
            reasons.append("hard_min_win_rate_net")
        if float(goal.hard_min_trades_per_week) > 0.0 and float(overall_tpw) < float(goal.hard_min_trades_per_week):
            reasons.append("hard_min_trades_per_week")
        max_top_share = min(max(float(goal.hard_max_concentration_top_share), 0.0), 1.0)
        if max_top_share < 1.0 and float(overall_top_share) > max_top_share:
            reasons.append("hard_max_concentration_top_share")
    return {
        "passed": len(reasons) == 0,
        "failed_reasons": reasons,
        "folds_total": int(len(net_by_fold)),
        "negative_folds": int(negative_count),
        "negative_fold_share": float(negative_share),
        "median_fold_net_ticks": float(median_net),
        "tail_cvar_ticks": float(tail_cvar),
        "overall_win_rate_net": float(overall_win_rate),
        "overall_trades_per_week": float(overall_tpw),
        "overall_concentration_top_share": float(overall_top_share),
        "thresholds": {
            "max_negative_fold_share": float(max_negative_fold_share),
            "min_median_fold_net_ticks": float(min_median_fold_net_ticks),
            "min_tail_cvar_ticks": float(min_tail_cvar_ticks),
            "hard_min_win_rate_net": float(goal.hard_min_win_rate_net) if goal is not None else 0.0,
            "hard_min_trades_per_week": float(goal.hard_min_trades_per_week) if goal is not None else 0.0,
            "hard_max_concentration_top_share": (
                float(goal.hard_max_concentration_top_share) if goal is not None else 1.0
            ),
        },
    }


def run_walk_forward(args: argparse.Namespace) -> dict[str, Any]:
    if bool(args.enable_news_gate) and bool(args.disable_news_gate):
        raise ValueError("news_gate_enable_disable_conflict")
    settings = load_settings(args.config)
    calendar = _build_calendar(settings)
    tz = ZoneInfo(settings.signal_engine.morning_plan.timezone)
    client = _build_client(settings)

    instruments = sorted(set(args.instrument))
    cluster_root_map = _parse_cluster_roots(list(args.cluster or []))
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
    holdout_start = _parse_iso_date(args.holdout_start_date) if args.holdout_start_date else None
    holdout_end = _parse_iso_date(args.holdout_end_date) if args.holdout_end_date else None
    if (holdout_start is None) ^ (holdout_end is None):
        raise ValueError("holdout_window_incomplete")
    if holdout_start is not None and holdout_end is not None and holdout_end < holdout_start:
        raise ValueError("holdout_end_before_start")
    decision_times = _parse_decision_times(list(args.decision_times or []), str(args.decision_time))
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
    news_gate_cfg = base_cfg.setdefault("news_gate", {})
    if isinstance(news_gate_cfg, dict):
        if bool(args.enable_news_gate):
            news_gate_cfg["enabled"] = True
        if bool(args.disable_news_gate):
            news_gate_cfg["enabled"] = False
        if args.news_gate_db_url:
            news_gate_cfg["db_url"] = str(args.news_gate_db_url).strip()
        if args.news_gate_lookback_minutes is not None:
            news_gate_cfg["lookback_minutes"] = max(int(args.news_gate_lookback_minutes), 1)
        if args.news_gate_min_impact_score is not None:
            news_gate_cfg["min_impact_score"] = float(args.news_gate_min_impact_score)
        if args.news_gate_min_confidence is not None:
            news_gate_cfg["min_confidence"] = float(args.news_gate_min_confidence)
        if args.news_gate_max_items is not None:
            news_gate_cfg["max_items"] = max(int(args.news_gate_max_items), 1)
        if args.news_gate_block_severity_threshold:
            news_gate_cfg["block_severity_threshold"] = str(args.news_gate_block_severity_threshold).strip().lower()
        if args.news_gate_reduce_severity_threshold:
            news_gate_cfg["reduce_severity_threshold"] = str(args.news_gate_reduce_severity_threshold).strip().lower()
        source_tokens = _parse_csv_tokens(list(args.news_gate_source or []))
        if source_tokens:
            news_gate_cfg["sources"] = source_tokens
        commodity_map_overrides = _parse_news_commodity_map(list(args.news_gate_commodity_map or []))
        if commodity_map_overrides:
            merged_map = dict(news_gate_cfg.get("commodity_map") or {})
            merged_map.update(commodity_map_overrides)
            news_gate_cfg["commodity_map"] = merged_map
        if args.news_gate_reduce_max_setups is not None:
            news_gate_cfg["reduce_max_setups"] = max(int(args.news_gate_reduce_max_setups), 1)
    costs = CostAssumptions(
        commission_ticks_per_side=float(args.commission_ticks_per_side),
        slippage_ticks_per_side=float(args.slippage_ticks_per_side),
        spread_half_ticks=float(args.spread_half_ticks),
    )
    cost_stress_mult = max(float(args.cost_stress_mult), 1e-9)
    stressed_base_costs = _apply_cost_stress(costs, cost_stress_mult)
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
        embargo_days=int(args.embargo_days),
        purge_days=int(args.purge_days),
    )

    folds: list[dict[str, Any]] = []
    aggregate_results: list[SetupResult] = []
    aggregate_planned_signals: list[PlannedSignal] = []
    min_train_trades = max(int(args.min_train_trades), 1)
    required_instruments = min(max(int(args.min_train_instruments_with_trades), 1), len(reporting_instruments))
    min_trades_per_instrument = max(int(args.min_trades_per_instrument), 1)
    robust_mad_penalty = max(float(args.robust_mad_penalty), 0.0)
    objective = str(args.selection_objective).strip().lower()
    goal_max_trades_per_week = max(float(args.goal_max_trades_per_week), 0.0)
    goal_min_trades_per_week = max(float(args.goal_min_trades_per_week), 0.0)
    if goal_max_trades_per_week > 0.0 and goal_max_trades_per_week < goal_min_trades_per_week:
        goal_max_trades_per_week = goal_min_trades_per_week
    goal_hard_min_win_rate_net = min(max(float(args.goal_hard_min_winrate_net), 0.0), 1.0)
    goal_hard_min_trades_per_week = max(float(args.goal_hard_min_trades_per_week), 0.0)
    goal_hard_max_top_share = min(max(float(args.goal_hard_max_concentration_top_share), 0.0), 1.0)
    goal = GoalConstraints(
        min_trades_per_week=goal_min_trades_per_week,
        max_trades_per_week=goal_max_trades_per_week,
        trade_freq_penalty=max(float(args.goal_trade_freq_penalty), 0.0),
        hard_min_win_rate_net=goal_hard_min_win_rate_net,
        hard_min_trades_per_week=goal_hard_min_trades_per_week,
        hard_max_concentration_top_share=goal_hard_max_top_share,
        hard_violation_penalty=max(float(args.goal_hard_violation_penalty), 0.0),
    )
    objective_scoring = ObjectiveScoringConfig(
        concentration_penalty_weight=max(float(args.objective_concentration_penalty_weight), 0.0),
        concentration_top_share_soft_cap=min(
            max(float(args.objective_concentration_top_share_soft_cap), 0.0), 1.0
        ),
        normalization_floor_ticks=max(float(args.objective_normalization_floor_ticks), 1e-9),
        tail_penalty_weight=max(float(args.objective_tail_penalty_weight), 0.0),
        tail_metric=str(args.objective_tail_metric).strip().lower(),
        tail_alpha=min(max(float(args.objective_tail_alpha), 1e-6), 1.0),
        lower_quantile=min(max(float(args.objective_tail_lower_quantile), 0.0), 1.0),
        sl_rate_penalty_weight=max(float(args.objective_sl_rate_penalty_weight), 0.0),
        exit_rate_penalty_weight=max(float(args.objective_exit_rate_penalty_weight), 0.0),
        exit_rate_soft_cap=min(max(float(args.objective_exit_rate_soft_cap), 0.0), 1.0),
    )
    objective_negative_fold_penalty = max(float(args.objective_negative_fold_penalty), 0.0)
    objective_subfold_days = max(int(args.objective_subfold_days), 0)
    probability_gate = ProbabilityGateConfig(
        enabled=bool(args.enable_probability_gate),
        min_n_effective=max(float(args.prob_min_n_effective), 0.0),
        min_expected_return_ticks=float(args.prob_min_expected_return_ticks),
        half_life_days=max(float(args.prob_half_life_days), 1e-9),
        dirichlet_alpha=max(float(args.prob_dirichlet_alpha), 1e-9),
        context_mode=str(args.prob_context_mode),
    )
    precision_side_tokens = tuple(
        sorted({token.upper() for token in _parse_csv_tokens(list(args.precision_allow_side or []))})
    )
    precision_setup_kind_tokens = tuple(
        sorted({token.upper() for token in _parse_csv_tokens(list(args.precision_allow_setup_kind or []))})
    )
    precision_stop_model_tokens = tuple(
        sorted({token.lower() for token in _parse_csv_tokens(list(args.precision_allow_stop_model or []))})
    )
    precision_time_tokens: list[str] = []
    for token in _parse_csv_tokens(list(args.precision_allow_decision_time or [])):
        precision_time_tokens.append(_parse_hhmm(token).isoformat(timespec="minutes"))
    precision_min_risk_ticks = int(args.precision_min_risk_ticks) if args.precision_min_risk_ticks is not None else None
    if precision_min_risk_ticks is not None and precision_min_risk_ticks < 0:
        raise ValueError("precision_min_risk_ticks_negative")
    precision_min_target_return_pct = (
        float(args.precision_min_target_return_pct)
        if args.precision_min_target_return_pct is not None
        else None
    )
    precision_filter = PrecisionFilterConfig(
        enabled=bool(args.enable_precision_filter),
        min_risk_ticks=precision_min_risk_ticks,
        min_target_return_pct=precision_min_target_return_pct,
        allowed_sides=precision_side_tokens,
        allowed_setup_kinds=precision_setup_kind_tokens,
        allowed_stop_models=precision_stop_model_tokens,
        allowed_decision_times=tuple(sorted(set(precision_time_tokens))),
        dedup_setup_ids=bool(args.precision_dedup_setup_ids),
    )
    collect_generator_rejection_trace = bool(args.collect_generator_rejection_trace)
    generator_rejection_trace_sample_limit = max(int(args.generator_rejection_trace_sample_limit), 0)
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
    last_selected_cfg: dict[str, Any] | None = None
    last_selected_cluster_overrides: dict[str, dict[str, Any]] | None = None
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
            base_costs=stressed_base_costs,
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
                            decision_times=decision_times,
                            tz=tz,
                            payload=payload,
                            tick_sizes=tick_sizes,
                            calendar=calendar,
                            costs=stressed_base_costs,
                            instrument_costs=fold_instrument_costs,
                            front_selector=front_selector,
                            eval_cache=run_eval_cache,
                            train_probability_gate=train_probability_gate,
                            cluster_root_map=cluster_root_map,
                            min_trades_per_instrument=min_trades_per_instrument,
                            robust_mad_penalty=robust_mad_penalty,
                            selection_objective=objective,
                            goal=goal,
                            objective_scoring=objective_scoring,
                            objective_negative_fold_penalty=objective_negative_fold_penalty,
                            objective_subfold_days=objective_subfold_days,
                            precision_filter=precision_filter,
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
                        decision_times=decision_times,
                        tz=tz,
                        payload=payload,
                        tick_sizes=tick_sizes,
                        calendar=calendar,
                        costs=stressed_base_costs,
                        instrument_costs=fold_instrument_costs,
                        front_selector=front_selector,
                        eval_cache=run_eval_cache,
                        train_probability_gate=train_probability_gate,
                        cluster_root_map=cluster_root_map,
                        min_trades_per_instrument=min_trades_per_instrument,
                        robust_mad_penalty=robust_mad_penalty,
                        selection_objective=objective,
                        goal=goal,
                        objective_scoring=objective_scoring,
                        objective_negative_fold_penalty=objective_negative_fold_penalty,
                        objective_subfold_days=objective_subfold_days,
                        precision_filter=precision_filter,
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
                            decision_times=decision_times,
                            tz=tz,
                            payload=payload,
                            tick_sizes=tick_sizes,
                            calendar=calendar,
                            costs=stressed_base_costs,
                            instrument_costs=fold_instrument_costs,
                            front_selector=front_selector,
                            eval_cache=run_eval_cache,
                            train_probability_gate=train_probability_gate,
                            cluster_root_map=cluster_root_map,
                            min_trades_per_instrument=min_trades_per_instrument,
                            robust_mad_penalty=robust_mad_penalty,
                            selection_objective=objective,
                            goal=goal,
                            objective_scoring=objective_scoring,
                            objective_negative_fold_penalty=objective_negative_fold_penalty,
                            objective_subfold_days=objective_subfold_days,
                            precision_filter=precision_filter,
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
        selected_global_overrides, selected_cluster_overrides = _split_cluster_overrides(selected_params)
        selected_cfg = _apply_overrides(base_cfg, selected_global_overrides)
        last_selected_cfg = selected_cfg
        last_selected_cluster_overrides = selected_cluster_overrides
        selected_train_rows, selected_train_summary, train_history, _ = _evaluate_window(
            period_start=train_start,
            period_end=train_end,
            instruments=instruments,
            decision_times=decision_times,
            tz=tz,
            cfg=selected_cfg,
            payload=payload,
            tick_sizes=tick_sizes,
            calendar=calendar,
            costs=stressed_base_costs,
            instrument_costs=fold_instrument_costs,
            front_selector=front_selector,
            eval_cache=run_eval_cache,
            probability_gate=train_probability_gate,
            cluster_overrides=selected_cluster_overrides,
            cluster_root_map=cluster_root_map,
            collect_history=True,
            precision_filter=precision_filter,
        )
        selected_train_metrics = asdict(
            _train_selection_metrics(
                summary=selected_train_summary,
                min_trades_per_instrument=min_trades_per_instrument,
                mad_penalty=robust_mad_penalty,
            )
        )
        normalized_metrics = _normalized_selection_components(
            summary=selected_train_summary,
            min_trades_per_instrument=min_trades_per_instrument,
            mad_penalty=robust_mad_penalty,
            scoring=objective_scoring,
        )
        selected_train_metrics.update(normalized_metrics)
        selected_negative_metrics = _negative_subfold_metrics(
            results=selected_train_rows,
            period_start=train_start,
            period_end=train_end,
            subfold_days=objective_subfold_days,
            penalty_weight=objective_negative_fold_penalty,
        )
        selected_train_metrics.update(selected_negative_metrics)
        selected_tail_metrics = _tail_risk_metrics(
            results=selected_train_rows,
            period_start=train_start,
            period_end=train_end,
            subfold_days=objective_subfold_days,
            tail_alpha=float(objective_scoring.tail_alpha),
            lower_quantile=float(objective_scoring.lower_quantile),
        )
        selected_train_metrics.update(selected_tail_metrics)
        selected_extra_penalty = 0.0
        selected_tail_reference = (
            float(selected_tail_metrics.get("subfold_net_ticks_cvar", 0.0))
            if str(objective_scoring.tail_metric).strip().lower() == "cvar"
            else float(selected_tail_metrics.get("subfold_net_ticks_lower_quantile", 0.0))
        )
        selected_tail_penalty = max(-selected_tail_reference, 0.0) * max(float(objective_scoring.tail_penalty_weight), 0.0)
        selected_sl_penalty = float(selected_train_summary.get("sl_rate", 0.0)) * max(
            float(objective_scoring.sl_rate_penalty_weight), 0.0
        )
        selected_exit_penalty = max(
            float(selected_train_summary.get("exit_rate", 0.0)) - float(objective_scoring.exit_rate_soft_cap), 0.0
        ) * max(float(objective_scoring.exit_rate_penalty_weight), 0.0)
        selected_kpi_penalty = float(selected_sl_penalty + selected_exit_penalty)
        selected_train_metrics["tail_penalty"] = float(selected_tail_penalty)
        selected_train_metrics["sl_rate_penalty"] = float(selected_sl_penalty)
        selected_train_metrics["exit_rate_penalty"] = float(selected_exit_penalty)
        selected_train_metrics["kpi_penalty"] = float(selected_kpi_penalty)
        if objective == "expectancy_net_ticks":
            selected_base_score = float(selected_train_summary.get("expectancy_net_ticks", 0.0))
        elif objective == "robust_normalized":
            selected_base_score = float(normalized_metrics.get("normalized_robust_score", float("-inf")))
            selected_extra_penalty = float(normalized_metrics.get("concentration_penalty", 0.0))
        else:
            selected_base_score = float(selected_train_metrics.get("robust_score", float("-inf")))
        selected_extra_penalty += float(selected_negative_metrics.get("negative_subfold_penalty", 0.0))
        selected_extra_penalty += float(selected_tail_penalty + selected_kpi_penalty)
        selected_train_metrics["selection_score"] = _goal_adjusted_selection_score(
            base_score=selected_base_score,
            summary=selected_train_summary,
            period_start=train_start,
            period_end=train_end,
            goal=goal,
            extra_penalty=selected_extra_penalty,
        )
        selected_train_metrics["trades_per_week"] = _trades_per_week(
            filled_trades=int(selected_train_summary.get("filled_trades", 0) or 0),
            period_start=train_start,
            period_end=train_end,
        )
        test_rows, test_summary, _, test_planned_rows = _evaluate_window(
            period_start=test_start,
            period_end=test_end,
            instruments=instruments,
            decision_times=decision_times,
            tz=tz,
            cfg=selected_cfg,
            payload=payload,
            tick_sizes=tick_sizes,
            calendar=calendar,
            costs=stressed_base_costs,
            instrument_costs=fold_instrument_costs,
            front_selector=front_selector,
            eval_cache=run_eval_cache,
            probability_gate=probability_gate,
            cluster_overrides=selected_cluster_overrides,
            cluster_root_map=cluster_root_map,
            initial_history=train_history,
            collect_history=True,
            precision_filter=precision_filter,
            collect_generator_rejection_trace=collect_generator_rejection_trace,
            generator_rejection_trace_sample_limit=generator_rejection_trace_sample_limit,
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
            test_rows, test_summary, _, test_planned_rows = _evaluate_window(
                period_start=test_start,
                period_end=test_end,
                instruments=instruments,
                decision_times=decision_times,
                tz=tz,
                cfg=selected_cfg,
                payload=payload,
                tick_sizes=tick_sizes,
                calendar=calendar,
                costs=stressed_base_costs,
                instrument_costs=fold_instrument_costs,
                front_selector=front_selector,
                eval_cache=run_eval_cache,
                probability_gate=None,
                cluster_overrides=selected_cluster_overrides,
                cluster_root_map=cluster_root_map,
                initial_history=None,
                collect_history=False,
                precision_filter=precision_filter,
                collect_generator_rejection_trace=collect_generator_rejection_trace,
                generator_rejection_trace_sample_limit=generator_rejection_trace_sample_limit,
            )
            probability_gate_fallback = {
                "applied": True,
                "reason": "min_filled_trades_per_fold",
                "min_filled_trades_per_fold": int(min_prob_filled_per_fold),
                "gated_test_summary": gated_test_summary,
            }
        aggregate_results.extend(test_rows)
        aggregate_planned_signals.extend(test_planned_rows)
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
                "planned_signals_count": int(len(test_planned_rows)),
            }
        )

    holdout_payload: dict[str, Any] | None = None
    if (
        holdout_start is not None
        and holdout_end is not None
        and last_selected_cfg is not None
        and last_selected_cluster_overrides is not None
    ):
        holdout_history: list[ProbHistoryEvent] | None = None
        if bool(probability_gate.enabled) and holdout_start > start_date:
            history_end = holdout_start - timedelta(days=1)
            if history_end >= start_date:
                _, _, holdout_history, _ = _evaluate_window(
                    period_start=start_date,
                    period_end=history_end,
                    instruments=instruments,
                    decision_times=decision_times,
                    tz=tz,
                    cfg=last_selected_cfg,
                    payload=payload,
                    tick_sizes=tick_sizes,
                    calendar=calendar,
                    costs=stressed_base_costs,
                    instrument_costs=None,
                    front_selector=front_selector,
                    eval_cache=run_eval_cache,
                    probability_gate=train_probability_gate,
                    cluster_overrides=last_selected_cluster_overrides,
                    cluster_root_map=cluster_root_map,
                    collect_history=True,
                    precision_filter=precision_filter,
                )
        holdout_rows, holdout_summary, _, holdout_planned = _evaluate_window(
            period_start=holdout_start,
            period_end=holdout_end,
            instruments=instruments,
            decision_times=decision_times,
            tz=tz,
            cfg=last_selected_cfg,
            payload=payload,
            tick_sizes=tick_sizes,
            calendar=calendar,
            costs=stressed_base_costs,
            instrument_costs=None,
            front_selector=front_selector,
            eval_cache=run_eval_cache,
            probability_gate=probability_gate,
            cluster_overrides=last_selected_cluster_overrides,
            cluster_root_map=cluster_root_map,
            initial_history=holdout_history,
            collect_history=False,
            precision_filter=precision_filter,
            collect_generator_rejection_trace=collect_generator_rejection_trace,
            generator_rejection_trace_sample_limit=generator_rejection_trace_sample_limit,
        )
        holdout_payload = {
            "start_date": holdout_start.isoformat(),
            "end_date": holdout_end.isoformat(),
            "summary": holdout_summary,
            "planned_signals_count": int(len(holdout_planned)),
            "sample_test_results": [asdict(item) for item in holdout_rows[: min(len(holdout_rows), 50)]],
            "sample_planned_signals": [asdict(item) for item in holdout_planned[: min(len(holdout_planned), 50)]],
        }

    overall = _summarize(aggregate_results, setups_total=sum(int(item["test_summary"]["setups_total"]) for item in folds))
    acceptance = _acceptance_summary(
        folds=folds,
        tail_alpha=float(objective_scoring.tail_alpha),
        max_negative_fold_share=float(args.accept_max_negative_fold_share),
        min_median_fold_net_ticks=float(args.accept_min_median_fold_net_ticks),
        min_tail_cvar_ticks=float(args.accept_min_tail_cvar_ticks),
        holdout_summary=(holdout_payload.get("summary") if holdout_payload is not None else None),
        overall_summary=overall,
        period_start=start_date,
        period_end=end_date,
        goal=goal,
    )
    generator_trace_counts_overall: dict[str, int] = {}
    generator_trace_samples_overall: list[dict[str, Any]] = []
    for fold in folds:
        test_summary = fold.get("test_summary") if isinstance(fold, dict) else None
        trace = test_summary.get("generator_rejection_trace") if isinstance(test_summary, dict) else None
        if not isinstance(trace, dict):
            continue
        counts = trace.get("counts")
        if isinstance(counts, dict):
            for key, value in counts.items():
                try:
                    parsed = int(value)
                except (TypeError, ValueError):
                    continue
                generator_trace_counts_overall[str(key)] = int(generator_trace_counts_overall.get(str(key), 0)) + parsed
        sample = trace.get("sample")
        if isinstance(sample, list):
            generator_trace_samples_overall.extend(sample[:10])
    if holdout_payload is not None:
        holdout_summary = holdout_payload.get("summary")
        trace = holdout_summary.get("generator_rejection_trace") if isinstance(holdout_summary, dict) else None
        if isinstance(trace, dict):
            counts = trace.get("counts")
            if isinstance(counts, dict):
                for key, value in counts.items():
                    try:
                        parsed = int(value)
                    except (TypeError, ValueError):
                        continue
                    generator_trace_counts_overall[str(key)] = int(generator_trace_counts_overall.get(str(key), 0)) + parsed
            sample = trace.get("sample")
            if isinstance(sample, list):
                generator_trace_samples_overall.extend(sample[:10])
    generator_trace_payload = {
        "total": int(sum(generator_trace_counts_overall.values())),
        "counts": dict(
            sorted(
                generator_trace_counts_overall.items(),
                key=lambda item: (-int(item[1]), str(item[0])),
            )
        ),
        "sample": list(generator_trace_samples_overall[:100]),
    }
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
            "decision_time": decision_times[0].isoformat(timespec="minutes"),
            "decision_times": [item.isoformat(timespec="minutes") for item in decision_times],
            "timezone": settings.signal_engine.morning_plan.timezone,
        },
        "cost_assumptions_ticks": asdict(costs),
        "cost_assumptions_ticks_stressed": asdict(stressed_base_costs),
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
            "cost_stress_mult": float(cost_stress_mult),
            "cluster_root_map": dict(cluster_root_map),
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
                "hard_min_win_rate_net": float(goal.hard_min_win_rate_net),
                "hard_min_trades_per_week": float(goal.hard_min_trades_per_week),
                "hard_max_concentration_top_share": float(goal.hard_max_concentration_top_share),
                "hard_violation_penalty": float(goal.hard_violation_penalty),
            },
            "objective_scoring": {
                "concentration_penalty_weight": float(objective_scoring.concentration_penalty_weight),
                "concentration_top_share_soft_cap": float(
                    objective_scoring.concentration_top_share_soft_cap
                ),
                "normalization_floor_ticks": float(objective_scoring.normalization_floor_ticks),
                "negative_fold_penalty": float(objective_negative_fold_penalty),
                "subfold_days": int(objective_subfold_days),
                "tail_penalty_weight": float(objective_scoring.tail_penalty_weight),
                "tail_metric": str(objective_scoring.tail_metric),
                "tail_alpha": float(objective_scoring.tail_alpha),
                "tail_lower_quantile": float(objective_scoring.lower_quantile),
                "sl_rate_penalty_weight": float(objective_scoring.sl_rate_penalty_weight),
                "exit_rate_penalty_weight": float(objective_scoring.exit_rate_penalty_weight),
                "exit_rate_soft_cap": float(objective_scoring.exit_rate_soft_cap),
            },
            "effective_min_target_return_pct": float(
                base_cfg.get("setups", {}).get("min_target_return_pct", 0.0)
            ),
            "precision_filter": {
                "enabled": bool(precision_filter.enabled),
                "min_risk_ticks": (
                    int(precision_filter.min_risk_ticks)
                    if precision_filter.min_risk_ticks is not None
                    else None
                ),
                "min_target_return_pct": (
                    float(precision_filter.min_target_return_pct)
                    if precision_filter.min_target_return_pct is not None
                    else None
                ),
                "allow_side": list(precision_filter.allowed_sides),
                "allow_setup_kind": list(precision_filter.allowed_setup_kinds),
                "allow_stop_model": list(precision_filter.allowed_stop_models),
                "allow_decision_time": list(precision_filter.allowed_decision_times),
                "dedup_setup_ids": bool(precision_filter.dedup_setup_ids),
            },
            "generator_rejection_trace": {
                "enabled": bool(collect_generator_rejection_trace),
                "sample_limit": int(generator_rejection_trace_sample_limit),
            },
            "news_gate": {
                "enabled": bool(base_cfg.get("news_gate", {}).get("enabled", False)),
                "db_url": str(base_cfg.get("news_gate", {}).get("db_url", "")),
                "lookback_minutes": int(base_cfg.get("news_gate", {}).get("lookback_minutes", 0)),
                "block_severity_threshold": str(
                    base_cfg.get("news_gate", {}).get("block_severity_threshold", "")
                ),
                "reduce_severity_threshold": str(
                    base_cfg.get("news_gate", {}).get("reduce_severity_threshold", "")
                ),
                "min_impact_score": float(base_cfg.get("news_gate", {}).get("min_impact_score", 0.0)),
                "min_confidence": float(base_cfg.get("news_gate", {}).get("min_confidence", 0.0)),
                "max_items": int(base_cfg.get("news_gate", {}).get("max_items", 0)),
                "reduce_max_setups": int(base_cfg.get("news_gate", {}).get("reduce_max_setups", 1)),
                "sources": list(base_cfg.get("news_gate", {}).get("sources", []) or []),
                "commodity_map": dict(base_cfg.get("news_gate", {}).get("commodity_map", {}) or {}),
            },
            "front_roll_avoid_expiry_days": int(front_roll_avoid_expiry_days),
            "min_train_trades": min_train_trades,
            "min_train_instruments_with_trades": required_instruments,
            "min_trades_per_instrument": min_trades_per_instrument,
            "robust_mad_penalty": robust_mad_penalty,
            "train_days": int(args.train_days),
            "test_days": int(args.test_days),
            "step_days": int(args.step_days),
            "embargo_days": int(args.embargo_days),
            "purge_days": int(args.purge_days),
        },
        "comparison_points": COMPARISON_POINTS,
        "folds": folds,
        "overall_test_summary": overall,
        "acceptance": acceptance,
        "generator_rejection_trace_overall": generator_trace_payload,
        "holdout": holdout_payload,
        "planned_signals_total": int(len(aggregate_planned_signals)),
        "planned_signals": [asdict(item) for item in aggregate_planned_signals],
        "sample_planned_signals": [
            asdict(item) for item in aggregate_planned_signals[: min(len(aggregate_planned_signals), 50)]
        ],
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
        "--cluster",
        action="append",
        default=[],
        help="Optional cluster mapping 'cluster=ROOT,ROOT'. Defaults: energy=BR,NG and metals=GD,SV,PL,PT.",
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
    parser.add_argument(
        "--decision-times",
        action="append",
        default=[],
        help="Optional repeated/comma-separated HH:MM list; overrides --decision-time when provided.",
    )
    parser.add_argument("--train-days", type=int, default=28)
    parser.add_argument("--test-days", type=int, default=7)
    parser.add_argument("--step-days", type=int, default=7)
    parser.add_argument("--embargo-days", type=int, default=0)
    parser.add_argument("--purge-days", type=int, default=0)
    parser.add_argument(
        "--tuning-profile",
        type=str,
        default="cost_aware_v2",
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
        default="intraday_goal_v3",
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
        choices=["robust_median_mad", "expectancy_net_ticks", "robust_normalized"],
    )
    parser.add_argument("--objective-concentration-penalty-weight", type=float, default=0.0)
    parser.add_argument("--objective-concentration-top-share-soft-cap", type=float, default=0.35)
    parser.add_argument("--objective-normalization-floor-ticks", type=float, default=1.0)
    parser.add_argument(
        "--objective-negative-fold-penalty",
        type=float,
        default=8.0,
        help="Penalty per negative train subfold (expectancy<0) when selecting params.",
    )
    parser.add_argument(
        "--objective-subfold-days",
        type=int,
        default=7,
        help="Train subfold length in days for negative-period penalty; 0 disables.",
    )
    parser.add_argument("--objective-tail-penalty-weight", type=float, default=0.0)
    parser.add_argument("--objective-tail-metric", type=str, default="cvar", choices=["cvar", "lower_quantile"])
    parser.add_argument("--objective-tail-alpha", type=float, default=0.2)
    parser.add_argument("--objective-tail-lower-quantile", type=float, default=0.2)
    parser.add_argument("--objective-sl-rate-penalty-weight", type=float, default=0.0)
    parser.add_argument("--objective-exit-rate-penalty-weight", type=float, default=0.0)
    parser.add_argument("--objective-exit-rate-soft-cap", type=float, default=0.35)
    parser.add_argument("--holdout-start-date", type=str, default=None, help="Optional fixed holdout start YYYY-MM-DD.")
    parser.add_argument("--holdout-end-date", type=str, default=None, help="Optional fixed holdout end YYYY-MM-DD.")
    parser.add_argument("--accept-max-negative-fold-share", type=float, default=0.6)
    parser.add_argument("--accept-min-median-fold-net-ticks", type=float, default=0.0)
    parser.add_argument("--accept-min-tail-cvar-ticks", type=float, default=-999999.0)
    parser.add_argument("--goal-min-target-return-pct", type=float, default=0.5)
    parser.add_argument("--goal-min-trades-per-week", type=float, default=2.0)
    parser.add_argument("--goal-max-trades-per-week", type=float, default=10.0)
    parser.add_argument("--goal-trade-freq-penalty", type=float, default=1.5)
    parser.add_argument("--goal-hard-min-winrate-net", type=float, default=0.0)
    parser.add_argument("--goal-hard-min-trades-per-week", type=float, default=0.0)
    parser.add_argument("--goal-hard-max-concentration-top-share", type=float, default=1.0)
    parser.add_argument("--goal-hard-violation-penalty", type=float, default=1_000_000.0)
    parser.add_argument("--min-train-trades", type=int, default=80)
    parser.add_argument("--min-train-instruments-with-trades", type=int, default=10)
    parser.add_argument("--min-trades-per-instrument", type=int, default=5)
    parser.add_argument("--robust-mad-penalty", type=float, default=0.5)
    parser.add_argument("--tick-size", action="append", default=[], help="Optional SECID=tick_size override.")
    parser.add_argument("--commission-ticks-per-side", type=float, default=0.5)
    parser.add_argument("--slippage-ticks-per-side", type=float, default=1.0)
    parser.add_argument("--spread-half-ticks", type=float, default=1.0)
    parser.add_argument(
        "--cost-stress-mult",
        type=float,
        default=1.0,
        help="Scale per-side cost assumptions for conservative stress (e.g. 1.5).",
    )
    parser.add_argument("--enable-precision-filter", action="store_true")
    parser.add_argument("--precision-min-risk-ticks", type=int, default=None)
    parser.add_argument("--precision-min-target-return-pct", type=float, default=None)
    parser.add_argument("--precision-allow-side", action="append", default=[])
    parser.add_argument("--precision-allow-setup-kind", action="append", default=[])
    parser.add_argument("--precision-allow-stop-model", action="append", default=[])
    parser.add_argument("--precision-allow-decision-time", action="append", default=[])
    parser.add_argument(
        "--collect-generator-rejection-trace",
        action="store_true",
        help="Collect setup-generator rule rejection trace in fold summaries.",
    )
    parser.add_argument(
        "--generator-rejection-trace-sample-limit",
        type=int,
        default=80,
        help="Max sampled rejection rows per window when trace collection is enabled (0 = unlimited).",
    )
    parser.add_argument(
        "--precision-dedup-setup-ids",
        action="store_true",
        help="When precision filter is enabled, keep only first occurrence of each setup_id per run.",
    )
    parser.add_argument("--enable-news-gate", action="store_true")
    parser.add_argument("--disable-news-gate", action="store_true")
    parser.add_argument("--news-gate-db-url", type=str, default=None)
    parser.add_argument("--news-gate-lookback-minutes", type=int, default=None)
    parser.add_argument("--news-gate-min-impact-score", type=float, default=None)
    parser.add_argument("--news-gate-min-confidence", type=float, default=None)
    parser.add_argument("--news-gate-max-items", type=int, default=None)
    parser.add_argument("--news-gate-block-severity-threshold", type=str, default=None)
    parser.add_argument("--news-gate-reduce-severity-threshold", type=str, default=None)
    parser.add_argument("--news-gate-source", action="append", default=[])
    parser.add_argument("--news-gate-commodity-map", action="append", default=[])
    parser.add_argument("--news-gate-reduce-max-setups", type=int, default=None)
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
