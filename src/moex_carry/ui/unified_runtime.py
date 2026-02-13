from __future__ import annotations

import hashlib
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from moex_carry.config import AppSettings
from moex_carry.domain.models import KeyRate
from moex_carry.domain.portfolio import PairSpec
from moex_carry.selection.universe import ASSET_CODE_ALIASES
from moex_carry.signal_replay import ReplayResult, load_pair_minute_series, run_minute_replay


@dataclass(frozen=True)
class _UniversePair:
    stock: str
    stock_name: str
    future: str
    expiry: date
    lot_size: float
    multiplier: float
    tick_size: float

    @property
    def pair_id(self) -> str:
        return f"{self.stock}|{self.future}"


@dataclass(frozen=True)
class _PairReplayCacheItem:
    created_at: datetime
    replay_result: ReplayResult
    source: str


@dataclass
class UnifiedMarketSnapshot:
    created_at: datetime
    top_pairs: pd.DataFrame
    signals: pd.DataFrame
    backtests: pd.DataFrame
    warnings: list[str]
    errors: list[str]


@dataclass(frozen=True)
class _SnapshotCacheItem:
    created_at: datetime
    signature: str
    snapshot: UnifiedMarketSnapshot


_SNAPSHOT_CACHE_LOCK = threading.Lock()
_SNAPSHOT_CACHE: _SnapshotCacheItem | None = None

_PAIR_REPLAY_CACHE_LOCK = threading.Lock()
_PAIR_REPLAY_CACHE: dict[str, _PairReplayCacheItem] = {}
_PAIR_REPLAY_CACHE_MAX = 512

_SCORE_MODEL = "probabilistic_edge_v1"
_SCORE_W_FLOOR = 0.35
_SCORE_W_ALPHA = 0.65
_SCORE_GATE_P_EXEC_THRESHOLD = 0.20
_SCORE_GATE_P_EARN_THRESHOLD = 0.10


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


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _row_get(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row.get(key)
        lower = key.lower()
        if lower in row:
            return row.get(lower)
        upper = key.upper()
        if upper in row:
            return row.get(upper)
    return None


def _normalize_series_dates(frame: pd.DataFrame) -> tuple[date | None, date | None]:
    if frame.empty or "date" not in frame.columns:
        return None, None
    work = pd.to_datetime(frame["date"], errors="coerce").dt.date.dropna()
    if work.empty:
        return None, None
    return min(work), max(work)


def _load_key_rates(data_dir: Path) -> list[KeyRate]:
    path = data_dir / "raw" / "key_rates.csv"
    if not path.exists():
        return []
    frame = pd.read_csv(path)
    if frame.empty:
        return []
    rates: list[KeyRate] = []
    for row in frame.to_dict("records"):
        day_raw = _row_get(row, "date")
        rate_raw = _row_get(row, "rate")
        day = pd.to_datetime(day_raw, errors="coerce").date() if day_raw else None
        rate = _safe_float(rate_raw)
        if day and rate is not None:
            rates.append(KeyRate(date=day, rate=rate))
    return rates


def _load_universe(settings: AppSettings, data_dir: Path, *, as_of: date) -> tuple[list[_UniversePair], list[str]]:
    warnings: list[str] = []
    shares_path = data_dir / "raw" / "shares.csv"
    futures_path = data_dir / "raw" / "futures.csv"
    if not shares_path.exists() or not futures_path.exists():
        missing = [str(path) for path in (shares_path, futures_path) if not path.exists()]
        warnings.append(f"unified_runtime:missing_raw_data:{','.join(missing)}")
        return [], warnings

    shares = pd.read_csv(shares_path)
    futures = pd.read_csv(futures_path)
    if shares.empty or futures.empty:
        warnings.append("unified_runtime:empty_raw_data")
        return [], warnings

    stock_names: dict[str, str] = {}
    for row in shares.to_dict("records"):
        secid_raw = _row_get(row, "SECID")
        if not secid_raw:
            continue
        secid = str(secid_raw).strip().upper()
        if not secid:
            continue
        name_raw = _row_get(row, "SHORTNAME", "SECNAME")
        stock_names[secid] = str(name_raw or secid)

    allowed_months = set(settings.spread_carry_alpha.allowed_expiry_months or [])
    allowed_years = set(settings.spread_carry_alpha.allowed_expiry_years or [])
    candidates: list[_UniversePair] = []
    for row in futures.to_dict("records"):
        secid_raw = _row_get(row, "SECID")
        asset_raw = _row_get(row, "ASSETCODE")
        if not secid_raw or not asset_raw:
            continue
        future = str(secid_raw).strip().upper()
        asset = str(asset_raw).strip().upper()
        stock = ASSET_CODE_ALIASES.get(asset, asset)
        if stock not in stock_names:
            continue
        expiry_raw = _row_get(row, "LASTTRADEDATE", "LASTTRADINGDAY")
        expiry = pd.to_datetime(expiry_raw, errors="coerce").date() if expiry_raw else None
        if expiry is None:
            continue
        if allowed_months and expiry.month not in allowed_months:
            continue
        if allowed_years and expiry.year not in allowed_years:
            continue
        lot_size = _safe_float(_row_get(row, "LOTVOLUME", "LOTSIZE", "LOT")) or 1.0
        multiplier = _safe_float(_row_get(row, "MULTIPLIER")) or 1.0
        tick_size = _safe_float(_row_get(row, "MINSTEP")) or 0.01
        candidates.append(
            _UniversePair(
                stock=stock,
                stock_name=stock_names.get(stock, stock),
                future=future,
                expiry=expiry,
                lot_size=lot_size,
                multiplier=multiplier,
                tick_size=tick_size,
            )
        )

    if not candidates:
        warnings.append("unified_runtime:no_mapped_pairs")
        return [], warnings

    front_only = bool(getattr(settings.ui, "unified_front_only", True))
    roll_days = max(int(getattr(settings.ui, "unified_front_roll_days", 7) or 0), 0)
    if not front_only:
        candidates.sort(key=lambda item: (item.expiry, item.stock, item.future))
        return candidates, warnings

    by_stock: dict[str, list[_UniversePair]] = {}
    for pair in candidates:
        by_stock.setdefault(pair.stock, []).append(pair)
    selected: list[_UniversePair] = []
    for stock, items in sorted(by_stock.items()):
        items.sort(key=lambda item: (item.expiry, item.future))
        pool = [item for item in items if (item.expiry - as_of).days >= roll_days]
        if not pool:
            pool = [item for item in items if (item.expiry - as_of).days >= 0]
        if not pool:
            pool = items
        choice = pool[0]
        if (choice.expiry - as_of).days < roll_days:
            warnings.append(
                f"unified_runtime:front_roll_short:{stock}:{choice.future}:dte={(choice.expiry - as_of).days}"
            )
        selected.append(choice)
    selected.sort(key=lambda item: (item.expiry, item.stock, item.future))
    return selected, warnings


def _alpha_signature(settings: AppSettings) -> str:
    payload = {
        "alpha": settings.spread_carry_alpha.model_dump(mode="python"),
        "costs": settings.costs.model_dump(mode="python"),
        "data": settings.data.model_dump(mode="python"),
        "ui_front_only": bool(getattr(settings.ui, "unified_front_only", True)),
        "ui_front_roll_days": int(getattr(settings.ui, "unified_front_roll_days", 7) or 0),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _pair_replay_key(
    *,
    settings: AppSettings,
    pair: _UniversePair,
    start_date: date,
    end_date: date,
) -> str:
    payload = {
        "sig": _alpha_signature(settings),
        "stock": pair.stock,
        "future": pair.future,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _evict_pair_cache_if_needed() -> None:
    if len(_PAIR_REPLAY_CACHE) <= _PAIR_REPLAY_CACHE_MAX:
        return
    ordered = sorted(_PAIR_REPLAY_CACHE.items(), key=lambda item: item[1].created_at)
    drop = len(_PAIR_REPLAY_CACHE) - _PAIR_REPLAY_CACHE_MAX
    for key, _ in ordered[:drop]:
        _PAIR_REPLAY_CACHE.pop(key, None)


def _pair_spec_from_universe(pair: _UniversePair) -> PairSpec:
    return PairSpec(
        stock_secid=pair.stock,
        future_secid=pair.future,
        expiry=pair.expiry,
        lot_size=pair.lot_size,
        multiplier=pair.multiplier,
        tick_size=pair.tick_size,
    )


def _compute_pair_replay(
    *,
    settings: AppSettings,
    data_dir: Path,
    pair: _UniversePair,
    start_date: date,
    end_date: date,
    key_rates: list[KeyRate],
) -> tuple[ReplayResult | None, str | None, str | None]:
    loaded = load_pair_minute_series(
        data_dir=data_dir,
        stock=pair.stock,
        future=pair.future,
        start_date=start_date,
        end_date=end_date,
    )
    if loaded is None:
        return None, None, "minute_series_not_found"
    replay_result = run_minute_replay(
        series_base=loaded.series_base,
        pair=_pair_spec_from_universe(pair),
        settings=settings,
        dividends=loaded.dividends,
        key_rates=key_rates,
    )
    if replay_result.replay.empty:
        return replay_result, loaded.source, "minute_replay_empty"
    return replay_result, loaded.source, None


def get_pair_replay(
    *,
    settings: AppSettings,
    data_dir: Path,
    pair: _UniversePair,
    start_date: date,
    end_date: date,
    key_rates: list[KeyRate],
    force: bool = False,
    ttl_sec: int = 120,
) -> tuple[ReplayResult | None, str | None, str | None]:
    cache_key = _pair_replay_key(
        settings=settings,
        pair=pair,
        start_date=start_date,
        end_date=end_date,
    )
    now = datetime.now(timezone.utc)
    if not force:
        with _PAIR_REPLAY_CACHE_LOCK:
            cached = _PAIR_REPLAY_CACHE.get(cache_key)
            if cached is not None:
                age = (now - cached.created_at).total_seconds()
                if age <= max(int(ttl_sec), 1):
                    return cached.replay_result, cached.source, None
    replay_result, source, error = _compute_pair_replay(
        settings=settings,
        data_dir=data_dir,
        pair=pair,
        start_date=start_date,
        end_date=end_date,
        key_rates=key_rates,
    )
    if replay_result is not None and error is None:
        with _PAIR_REPLAY_CACHE_LOCK:
            _PAIR_REPLAY_CACHE[cache_key] = _PairReplayCacheItem(
                created_at=now,
                replay_result=replay_result,
                source=str(source or ""),
            )
            _evict_pair_cache_if_needed()
    return replay_result, source, error


def _value_from_row(frame: pd.DataFrame, column: str) -> Any:
    if frame.empty or column not in frame.columns:
        return None
    value = frame.iloc[-1].get(column)
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def _resolve_target_annual_rate(
    *,
    settings: AppSettings,
    key_rates: list[KeyRate],
    as_of: date | None,
) -> float:
    alpha = settings.spread_carry_alpha
    configured = _safe_float(getattr(alpha, "annual_target_threshold", None))
    if configured is not None:
        return configured
    policy_rate = _safe_float(getattr(alpha, "r_cb_annual", None))
    if policy_rate is not None:
        return policy_rate
    if not key_rates:
        return 0.0
    ordered = sorted((item for item in key_rates if item.rate is not None), key=lambda item: item.date)
    if not ordered:
        return 0.0
    if as_of is not None:
        eligible = [item for item in ordered if item.date <= as_of]
        if eligible:
            return float(eligible[-1].rate)
    return float(ordered[-1].rate)


def _build_pair_rows(
    *,
    pair: _UniversePair,
    replay: ReplayResult,
    source: str | None,
    settings: AppSettings,
    key_rates: list[KeyRate],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    frame = replay.replay
    metrics = replay.metrics
    latest = frame.iloc[-1] if not frame.empty else pd.Series(dtype=object)
    signal_action = str(latest.get("signal_action") or "hold").lower()
    signal_direction = latest.get("signal_direction")
    if signal_action == "enter" and not signal_direction:
        signal_direction = "cash_and_carry"

    latest_date_raw = latest.get("date")
    latest_date = pd.to_datetime(latest_date_raw, errors="coerce").date() if latest_date_raw is not None else None
    score_target_annual = _resolve_target_annual_rate(settings=settings, key_rates=key_rates, as_of=latest_date)

    floor_rate_annual = _safe_float(latest.get("floor_rate_annual")) or 0.0
    score_floor = float(floor_rate_annual - score_target_annual)
    score_alpha = (
        _safe_float(metrics.avg_trade_return_annual_operational_last5)
        if metrics.avg_trade_return_annual_operational_last5 is not None
        else _safe_float(metrics.avg_trade_return_annual_fill_to_fill_last5)
    )
    score_alpha = float(score_alpha or 0.0)

    unfilled_entry_rate = _safe_float(metrics.unfilled_entry_rate)
    unfilled_exit_rate = _safe_float(metrics.unfilled_exit_rate)
    forced_exit_rate = _safe_float(metrics.forced_exit_rate)
    share_target_pass = _safe_float(metrics.share_target_pass)

    p_exec = _clip01(
        (1.0 - (unfilled_entry_rate if unfilled_entry_rate is not None else 1.0))
        * (1.0 - (unfilled_exit_rate or 0.0))
        * (1.0 - (forced_exit_rate or 0.0))
    )
    p_earn = _clip01(p_exec * (share_target_pass or 0.0))
    score_edge_raw_annual = float(_SCORE_W_FLOOR * score_floor + _SCORE_W_ALPHA * score_alpha)
    signal_score = float(p_exec * score_edge_raw_annual)
    score_gate_pass = bool(
        p_exec >= _SCORE_GATE_P_EXEC_THRESHOLD and p_earn >= _SCORE_GATE_P_EARN_THRESHOLD
    )

    entry_spread = _safe_float(latest.get("entry_spread_pct_exec"))
    tp_net = _safe_float(latest.get("tp_net"))
    sl_net = _safe_float(latest.get("sl_net"))
    tp_spread_level = (
        float(entry_spread + tp_net) if entry_spread is not None and tp_net is not None else None
    )
    sl_spread_level = (
        float(entry_spread - sl_net) if entry_spread is not None and sl_net is not None else None
    )
    signal_metrics = {
        "spread_pct": _safe_float(latest.get("spread_pct")),
        "rtc_pct": _safe_float(latest.get("rtc_pct")),
        "floor_rate_annual": floor_rate_annual,
        "tp_net": tp_net,
        "sl_net": sl_net,
        "score_model": _SCORE_MODEL,
        "score_target_annual": score_target_annual,
        "score_floor": score_floor,
        "score_floor_excess_annual": score_floor,
        "score_alpha": score_alpha,
        "score_edge_raw_annual": score_edge_raw_annual,
        "score_exec_probability": p_exec,
        "score_earn_probability": p_earn,
        "score_gate_exec_threshold": _SCORE_GATE_P_EXEC_THRESHOLD,
        "score_gate_earn_threshold": _SCORE_GATE_P_EARN_THRESHOLD,
        "score_gate_pass": score_gate_pass,
        "total_score": signal_score,
        "avg_trade_return_annual_recent": _safe_float(metrics.avg_trade_return_annual_fill_to_fill_last5),
        "avg_trade_return_annual_operational_recent": _safe_float(metrics.avg_trade_return_annual_operational_last5),
        "share_target_pass": share_target_pass,
        "unfilled_entry_rate": unfilled_entry_rate,
        "unfilled_exit_rate": unfilled_exit_rate,
        "forced_exit_rate": forced_exit_rate,
        "entry_spread_pct_min": entry_spread,
        "entry_spread_pct_max": entry_spread,
        "tp_spread_pct_level": tp_spread_level,
        "sl_spread_pct_level": sl_spread_level,
        "forecast_exit_days": _safe_float(_value_from_row(frame, "trade_hold_days")),
        "forecast_exit_date": None,
        "entry_price_tolerance_pct": None,
        "source": source,
    }
    decision = "ENTER_OK" if signal_action == "enter" else ("EXIT" if signal_action == "exit" else "HOLD")
    reasons = [f"replay_{signal_action}"]
    if metrics.error:
        reasons.append(metrics.error)

    top_row: dict[str, Any] = {
        "stock": pair.stock,
        "stock_name": pair.stock_name,
        "future": pair.future,
        "expiry": pair.expiry.isoformat(),
        "spot": _safe_float(latest.get("spot_mid")),
        "future_price": _safe_float(latest.get("future_mid")),
        "spread_mid": _safe_float(latest.get("spread_mid")),
        "spread_pct": _safe_float(latest.get("spread_pct")),
        "rtc_pct": _safe_float(latest.get("rtc_pct")),
        "floor_rate_annual": floor_rate_annual,
        "score_model": _SCORE_MODEL,
        "score_target_annual": score_target_annual,
        "score_floor": score_floor,
        "score_floor_excess_annual": score_floor,
        "score_alpha": score_alpha,
        "score_edge_raw_annual": score_edge_raw_annual,
        "score_exec_probability": p_exec,
        "score_earn_probability": p_earn,
        "score_gate_exec_threshold": _SCORE_GATE_P_EXEC_THRESHOLD,
        "score_gate_earn_threshold": _SCORE_GATE_P_EARN_THRESHOLD,
        "score_gate_pass": score_gate_pass,
        "total_score": signal_score,
        "decision": decision,
        "signal_action": signal_action,
        "signal_direction": signal_direction,
        "signal_score": signal_score,
        "signal_reasons": reasons,
        "signal_metrics": signal_metrics,
        "zscore": _safe_float(latest.get("zscore")),
        "tp_net": tp_net,
        "sl_net": sl_net,
        "entry_spread_pct_min": entry_spread,
        "entry_spread_pct_max": entry_spread,
        "tp_spread_pct_level": tp_spread_level,
        "sl_spread_pct_level": sl_spread_level,
        "forecast_exit_days": _safe_float(_value_from_row(frame, "trade_hold_days")),
        "forecast_exit_date": None,
        "avg_trade_return_annual_recent": _safe_float(metrics.avg_trade_return_annual_fill_to_fill_last5),
        "avg_trade_return_annual_operational_recent": _safe_float(metrics.avg_trade_return_annual_operational_last5),
        "share_target_pass": share_target_pass,
        "unfilled_entry_rate": unfilled_entry_rate,
        "unfilled_exit_rate": unfilled_exit_rate,
        "forced_exit_rate": forced_exit_rate,
        "rows": int(metrics.rows),
        "days": int(metrics.days),
        "entry_signals": int(metrics.entry_signals),
        "exit_signals": int(metrics.exit_signals),
        "trades_closed": int(metrics.trades_closed),
        "avg_entry_wait_min_closed": _safe_float(metrics.avg_entry_wait_min_closed),
        "avg_exit_wait_min_closed": _safe_float(metrics.avg_exit_wait_min_closed),
        "source": source,
    }
    signal_row = {
        "stock": pair.stock,
        "stock_name": pair.stock_name,
        "future": pair.future,
        "signal_action": signal_action,
        "signal_direction": signal_direction,
        "signal_score": signal_score,
        "score_model": _SCORE_MODEL,
        "score_target_annual": score_target_annual,
        "score_floor": score_floor,
        "score_floor_excess_annual": score_floor,
        "score_alpha": score_alpha,
        "score_edge_raw_annual": score_edge_raw_annual,
        "score_exec_probability": p_exec,
        "score_earn_probability": p_earn,
        "score_gate_exec_threshold": _SCORE_GATE_P_EXEC_THRESHOLD,
        "score_gate_earn_threshold": _SCORE_GATE_P_EARN_THRESHOLD,
        "score_gate_pass": score_gate_pass,
        "total_score": signal_score,
        "spread_pct": _safe_float(latest.get("spread_pct")),
        "floor_rate_annual": floor_rate_annual,
        "entry_spread_pct_min": entry_spread,
        "entry_spread_pct_max": entry_spread,
        "tp_spread_pct_level": tp_spread_level,
        "sl_spread_pct_level": sl_spread_level,
        "forecast_exit_days": _safe_float(_value_from_row(frame, "trade_hold_days")),
        "forecast_exit_date": None,
        "tp_net": tp_net,
        "sl_net": sl_net,
        "avg_trade_return_annual_recent": _safe_float(metrics.avg_trade_return_annual_fill_to_fill_last5),
        "avg_trade_return_annual_operational_recent": _safe_float(metrics.avg_trade_return_annual_operational_last5),
        "share_target_pass": share_target_pass,
        "unfilled_entry_rate": unfilled_entry_rate,
        "unfilled_exit_rate": unfilled_exit_rate,
        "forced_exit_rate": forced_exit_rate,
        "signal_reasons": reasons,
        "signal_metrics": signal_metrics,
    }
    backtest_row = {
        "stock": pair.stock,
        "future": pair.future,
        "cagr": _safe_float(metrics.avg_trade_return_annual_operational_last5),
        "max_drawdown": None,
        "sharpe": None,
        "hit_rate": _safe_float(metrics.share_target_pass),
        "turnover": None,
        "share_alpha_exits": None,
        "avg_hold_days": _safe_float(_value_from_row(frame, "trade_hold_days")),
        "trades_closed": int(metrics.trades_closed),
        "unfilled_entry_rate": _safe_float(metrics.unfilled_entry_rate),
        "forced_exit_rate": _safe_float(metrics.forced_exit_rate),
        "avg_entry_wait_min_closed": _safe_float(metrics.avg_entry_wait_min_closed),
        "avg_exit_wait_min_closed": _safe_float(metrics.avg_exit_wait_min_closed),
    }
    return top_row, signal_row, backtest_row


def _build_snapshot_signature(
    *,
    settings: AppSettings,
    data_dir: Path,
    as_of: date,
    lookback_days: int,
    max_pairs: int | None,
) -> str:
    payload = {
        "settings_sig": _alpha_signature(settings),
        "data_dir": str(data_dir),
        "as_of": as_of.isoformat(),
        "lookback_days": int(lookback_days),
        "max_pairs": int(max_pairs) if max_pairs is not None else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def build_unified_market_snapshot(
    settings: AppSettings,
    data_dir: Path,
    *,
    force: bool = False,
    ttl_sec: int = 120,
    as_of: date | None = None,
    max_pairs: int | None = None,
) -> UnifiedMarketSnapshot:
    global _SNAPSHOT_CACHE
    now = datetime.now(timezone.utc)
    as_of_date = as_of or now.date()
    lookback_days = max(int(settings.data.compute_lookback_days or 120), 1)
    signature = _build_snapshot_signature(
        settings=settings,
        data_dir=data_dir,
        as_of=as_of_date,
        lookback_days=lookback_days,
        max_pairs=max_pairs,
    )
    if not force:
        with _SNAPSHOT_CACHE_LOCK:
            if _SNAPSHOT_CACHE is not None and _SNAPSHOT_CACHE.signature == signature:
                age = (now - _SNAPSHOT_CACHE.created_at).total_seconds()
                if age <= max(int(ttl_sec), 1):
                    return _SNAPSHOT_CACHE.snapshot

    key_rates = _load_key_rates(data_dir)
    universe, warnings = _load_universe(settings, data_dir, as_of=as_of_date)
    if max_pairs is not None and max_pairs > 0:
        universe = universe[: max_pairs]
    start_date = as_of_date - timedelta(days=lookback_days)
    end_date = as_of_date

    top_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    backtest_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    def _compute(pair: _UniversePair) -> tuple[_UniversePair, ReplayResult | None, str | None, str | None]:
        replay_result, source, error = get_pair_replay(
            settings=settings,
            data_dir=data_dir,
            pair=pair,
            start_date=start_date,
            end_date=end_date,
            key_rates=key_rates,
            force=force,
            ttl_sec=ttl_sec,
        )
        return pair, replay_result, source, error

    workers = max(int(getattr(settings.ui, "unified_pair_workers", 4) or 0), 1)
    if workers <= 1:
        results = [_compute(pair) for pair in universe]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_compute, universe))

    for pair, replay_result, source, error in results:
        if error:
            errors.append(f"{pair.pair_id}:{error}")
            continue
        if replay_result is None:
            errors.append(f"{pair.pair_id}:replay_none")
            continue
        top_row, signal_row, backtest_row = _build_pair_rows(
            pair=pair,
            replay=replay_result,
            source=source,
            settings=settings,
            key_rates=key_rates,
        )
        top_rows.append(top_row)
        signal_rows.append(signal_row)
        backtest_rows.append(backtest_row)

    top_pairs = pd.DataFrame(top_rows)
    if not top_pairs.empty:
        top_pairs = top_pairs.sort_values(
            ["signal_score", "avg_trade_return_annual_operational_recent"],
            ascending=[False, False],
        ).reset_index(drop=True)
    signals = pd.DataFrame(signal_rows)
    if not signals.empty:
        signals = signals.sort_values(
            ["signal_score", "avg_trade_return_annual_operational_recent"],
            ascending=[False, False],
        ).reset_index(drop=True)
    backtests = pd.DataFrame(backtest_rows)
    if not backtests.empty:
        backtests = backtests.sort_values(
            ["cagr", "hit_rate"],
            ascending=[False, False],
        ).reset_index(drop=True)

    snapshot = UnifiedMarketSnapshot(
        created_at=now,
        top_pairs=top_pairs,
        signals=signals,
        backtests=backtests,
        warnings=warnings,
        errors=errors,
    )
    with _SNAPSHOT_CACHE_LOCK:
        _SNAPSHOT_CACHE = _SnapshotCacheItem(
            created_at=now,
            signature=signature,
            snapshot=snapshot,
        )
    return snapshot


def build_unified_spread_series(
    settings: AppSettings,
    data_dir: Path,
    *,
    stock: str,
    future: str,
    window_days: int,
    full_life: bool,
    ttl_sec: int = 120,
) -> pd.DataFrame:
    stock_norm = str(stock).strip().upper()
    future_norm = str(future).strip().upper()
    as_of = datetime.now(timezone.utc).date()
    lookback = 3650 if full_life else max(int(window_days), 1)
    start_date = as_of - timedelta(days=lookback)
    end_date = as_of
    key_rates = _load_key_rates(data_dir)

    universe, _ = _load_universe(settings, data_dir, as_of=as_of)
    pair = next(
        (item for item in universe if item.stock == stock_norm and item.future == future_norm),
        None,
    )
    if pair is None:
        # Build a minimal fallback pair from raw futures metadata if the pair is not in front-universe.
        futures_path = data_dir / "raw" / "futures.csv"
        if not futures_path.exists():
            return pd.DataFrame()
        futures = pd.read_csv(futures_path)
        fallback = None
        for row in futures.to_dict("records"):
            secid = str(_row_get(row, "SECID") or "").strip().upper()
            if secid != future_norm:
                continue
            asset = str(_row_get(row, "ASSETCODE") or "").strip().upper()
            asset = ASSET_CODE_ALIASES.get(asset, asset)
            expiry_raw = _row_get(row, "LASTTRADEDATE", "LASTTRADINGDAY")
            expiry = pd.to_datetime(expiry_raw, errors="coerce").date() if expiry_raw else None
            if expiry is None:
                continue
            fallback = _UniversePair(
                stock=asset,
                stock_name=asset,
                future=secid,
                expiry=expiry,
                lot_size=_safe_float(_row_get(row, "LOTVOLUME", "LOTSIZE", "LOT")) or 1.0,
                multiplier=_safe_float(_row_get(row, "MULTIPLIER")) or 1.0,
                tick_size=_safe_float(_row_get(row, "MINSTEP")) or 0.01,
            )
            break
        if fallback is None:
            return pd.DataFrame()
        pair = fallback
    replay_result, _, error = get_pair_replay(
        settings=settings,
        data_dir=data_dir,
        pair=pair,
        start_date=start_date,
        end_date=end_date,
        key_rates=key_rates,
        force=False,
        ttl_sec=ttl_sec,
    )
    if error or replay_result is None:
        return pd.DataFrame()
    frame = replay_result.replay.copy()
    if frame.empty:
        return frame
    if not full_life:
        min_day = as_of - timedelta(days=max(int(window_days), 1))
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
        frame = frame[frame["date"] >= min_day].copy()
    return frame.reset_index(drop=True)


def persist_snapshot_to_csv(snapshot: UnifiedMarketSnapshot, data_dir: Path) -> None:
    output = data_dir / "output"
    output.mkdir(parents=True, exist_ok=True)
    if not snapshot.top_pairs.empty:
        snapshot.top_pairs.to_csv(output / "top_pairs.csv", index=False)
    if not snapshot.signals.empty:
        snapshot.signals.to_csv(output / "signals.csv", index=False)
    if not snapshot.backtests.empty:
        snapshot.backtests.to_csv(output / "backtest_summary.csv", index=False)


def resolve_series_date_range(frame: pd.DataFrame) -> tuple[date | None, date | None]:
    return _normalize_series_dates(frame)
