from __future__ import annotations

import argparse
import copy
import itertools
import json
import sqlite3
import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from moex_carry.config import AppSettings, load_settings
from moex_carry.data.moex_iss import MoexIssClient
from moex_carry.signal_engine.core.calendar import MarketCalendar, parse_time_window
from moex_carry.signal_engine.core.math_utils import price_to_ticks
from moex_carry.signal_engine.core.ohlcv import resample_ohlcv
from moex_carry.signal_engine.core.types import Candle, Setup, Side, TF
from moex_carry.signal_engine.data.candles import InMemoryCandleProvider
from moex_carry.signal_engine.plan.builder import MorningPlanBuilder

DEFAULT_TUNING_GRID: dict[str, list[float]] = {
    "execution.buffer_atr_mult": [0.08, 0.10, 0.12],
    "setups.rr_default": [1.4, 1.6],
    "setups.pullback_max_dist_atr_mult": [0.8, 1.0],
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
            tick_size = 0.01
        if tick_size <= 0:
            tick_size = 0.01
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
            d1 = _fetch_candles_cached(
                conn=conn,
                interval=24,
                offline_only=offline_only,
                refresh_cache=refresh_cache,
                stats=stats,
                **fetch_args,
            )
            h1 = _fetch_candles_cached(
                conn=conn,
                interval=60,
                offline_only=offline_only,
                refresh_cache=refresh_cache,
                stats=stats,
                **fetch_args,
            )
            m1 = _fetch_candles_cached(
                conn=conn,
                interval=1,
                offline_only=offline_only,
                refresh_cache=refresh_cache,
                stats=stats,
                **fetch_args,
            )
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
) -> tuple[list[SetupResult], dict[str, Any]]:
    provider = InMemoryCandleProvider(payload)
    builders = {instrument_id: MorningPlanBuilder(provider, calendar, cfg) for instrument_id in instruments}
    rows: list[SetupResult] = []
    setups_total = 0
    for day in _iter_days(period_start, period_end):
        as_of_ts = datetime.combine(day, decision_time, tzinfo=tz)
        if not calendar.is_trading_time(as_of_ts):
            continue
        for instrument_id in instruments:
            builder = builders[instrument_id]
            tick_size = float(tick_sizes[instrument_id])
            plan = builder.build_plan(as_of_ts=as_of_ts, instrument_id=instrument_id, tick_size=tick_size)
            setups_total += len(plan.setups)
            m5_rows = payload.get((instrument_id, TF.M5), [])
            for setup in plan.setups:
                rows.append(
                    _simulate_setup(
                        instrument_id=instrument_id,
                        as_of_ts=as_of_ts,
                        setup=setup,
                        m5_rows=m5_rows,
                        tick_size=tick_size,
                        calendar=calendar,
                        costs=costs,
                    )
                )
    summary = _summarize(rows, setups_total=setups_total)
    return rows, summary


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
    )

    if bool(args.prefetch_only):
        return {
            "generated_at": datetime.now(tz=ZoneInfo("UTC")).isoformat(),
            "mode": "cache_prefetch_only",
            "instruments": instruments,
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
    costs = CostAssumptions(
        commission_ticks_per_side=float(args.commission_ticks_per_side),
        slippage_ticks_per_side=float(args.slippage_ticks_per_side),
        spread_half_ticks=float(args.spread_half_ticks),
    )
    grid = DEFAULT_TUNING_GRID
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
    required_instruments = min(max(int(args.min_train_instruments_with_trades), 1), len(instruments))
    min_trades_per_instrument = max(int(args.min_trades_per_instrument), 1)
    robust_mad_penalty = max(float(args.robust_mad_penalty), 0.0)
    objective = str(args.selection_objective).strip().lower()
    for idx, window in enumerate(windows, start=1):
        train_start = window["train_start"]
        train_end = window["train_end"]
        test_start = window["test_start"]
        test_end = window["test_end"]
        train_scores: list[dict[str, Any]] = []
        for combo in combinations:
            cfg = _apply_overrides(base_cfg, combo)
            _, train_summary = _evaluate_window(
                period_start=train_start,
                period_end=train_end,
                instruments=instruments,
                decision_time=decision_time,
                tz=tz,
                cfg=cfg,
                payload=payload,
                tick_sizes=tick_sizes,
                calendar=calendar,
                costs=costs,
            )
            train_scores.append(
                {
                    "params": combo,
                    "summary": train_summary,
                    "metrics": asdict(
                        _train_selection_metrics(
                            summary=train_summary,
                            min_trades_per_instrument=min_trades_per_instrument,
                            mad_penalty=robust_mad_penalty,
                        )
                    ),
                }
            )
        eligible = [
            row
            for row in train_scores
            if int(row["summary"]["filled_trades"]) >= min_train_trades
            and int(row["metrics"]["instruments_with_trades"]) >= required_instruments
            and int(row["metrics"]["robust_instruments"]) >= required_instruments
        ]
        if objective == "expectancy_net_ticks":
            ranked = sorted(
                eligible,
                key=lambda row: (
                    float(row["summary"]["expectancy_net_ticks"]),
                    float(row["summary"]["net_ticks_sum"]),
                    int(row["summary"]["filled_trades"]),
                ),
                reverse=True,
            )
        else:
            ranked = sorted(
                eligible,
                key=lambda row: (
                    float(row["metrics"]["robust_score"]),
                    float(row["metrics"]["median_expectancy"]),
                    float(row["summary"]["expectancy_net_ticks"]),
                    float(row["summary"]["net_ticks_sum"]),
                    int(row["summary"]["filled_trades"]),
                ),
                reverse=True,
            )
        selected = ranked[0] if ranked else next(
            (row for row in train_scores if row["params"] == default_combo),
            train_scores[0],
        )
        selected_cfg = _apply_overrides(base_cfg, selected["params"])
        test_rows, test_summary = _evaluate_window(
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
        )
        aggregate_results.extend(test_rows)
        folds.append(
            {
                "fold_id": idx,
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(),
                "selected_params": selected["params"],
                "train_summary": selected["summary"],
                "train_selection_metrics": selected["metrics"],
                "test_summary": test_summary,
            }
        )

    overall = _summarize(aggregate_results, setups_total=sum(int(item["test_summary"]["setups_total"]) for item in folds))
    return {
        "generated_at": datetime.now(tz=ZoneInfo("UTC")).isoformat(),
        "mode": "causal_walk_forward",
        "instruments": instruments,
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
            "grid": grid,
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
    parser.add_argument("--start-date", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--decision-time", type=str, default="12:00", help="HH:MM in exchange timezone.")
    parser.add_argument("--train-days", type=int, default=20)
    parser.add_argument("--test-days", type=int, default=5)
    parser.add_argument("--step-days", type=int, default=5)
    parser.add_argument(
        "--selection-objective",
        type=str,
        default="robust_median_mad",
        choices=["robust_median_mad", "expectancy_net_ticks"],
    )
    parser.add_argument("--min-train-trades", type=int, default=80)
    parser.add_argument("--min-train-instruments-with-trades", type=int, default=8)
    parser.add_argument("--min-trades-per-instrument", type=int, default=3)
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
