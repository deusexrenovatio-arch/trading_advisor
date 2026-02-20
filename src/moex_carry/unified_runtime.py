from __future__ import annotations

import hashlib
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from moex_carry.analytics.alpha import alpha_metrics
from moex_carry.config import AppSettings
from moex_carry.domain.models import KeyRate
from moex_carry.domain.portfolio import PairSpec
from moex_carry.minute_ingest.runner import IngestPair, PairIngestResult
from moex_carry.selection.universe import ASSET_CODE_ALIASES
from moex_carry.signal_replay.incremental import ReplayMutation, run_true_incremental_replay
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
    data_watermark: str | None


@dataclass(frozen=True)
class _PairReplayFetch:
    replay_result: ReplayResult | None
    source: str | None
    error: str | None
    cache_hit: bool
    skip_reason: str | None
    fallback_reason: str | None
    replay_mode: str


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


@dataclass(frozen=True)
class PairReplayTelemetry:
    pair_id: str
    cache_source: str
    skip_reason: str | None
    fallback_reason: str | None


@dataclass(frozen=True)
class RefreshTelemetry:
    incremental_enabled: bool
    data_watermark_before: str | None
    data_watermark_after: str | None
    pairs_total: int
    pairs_recomputed: int
    pairs_reused: int
    pairs_skipped: int
    skip_reason: str | None


_SNAPSHOT_CACHE_LOCK = threading.Lock()
_SNAPSHOT_CACHE: _SnapshotCacheItem | None = None

_PAIR_REPLAY_CACHE_LOCK = threading.Lock()
_PAIR_REPLAY_CACHE: dict[str, _PairReplayCacheItem] = {}
_PAIR_REPLAY_CACHE_MAX_HARD_LIMIT = 512
_PAIR_REPLAY_CACHE_DEFAULT_MAX = 64

_LAST_REFRESH_TELEMETRY_LOCK = threading.Lock()
_LAST_REFRESH_TELEMETRY = RefreshTelemetry(
    incremental_enabled=False,
    data_watermark_before=None,
    data_watermark_after=None,
    pairs_total=0,
    pairs_recomputed=0,
    pairs_reused=0,
    pairs_skipped=0,
    skip_reason=None,
)

_SCORE_MODEL = "probabilistic_edge_v1"
_SCORE_W_FLOOR = 0.35
_SCORE_W_ALPHA = 0.65
_SCORE_GATE_P_EXEC_THRESHOLD = 0.60
_SCORE_GATE_P_EARN_THRESHOLD = 0.25
_SCORE_GATE_SIGNAL_SCORE_MIN = 0.0
_SCORE_GATE_FLOOR_EXCESS_ANNUAL_MIN = 0.0
_SCORE_GATE_MIN_DAYS = 30
_SCORE_GATE_MIN_CLOSED_TRADES = 3
_SCORE_EARN_BLEND_HISTORY_WEIGHT = 0.50
_SCORE_EARN_BLEND_FORWARD_WEIGHT = 0.50
_DEFAULT_ENTRY_PRICE_TOLERANCE_PCT = 0.0015
_FORWARD_PATH_PRIOR_TP = 0.50
_FORWARD_PATH_PRIOR_SL = 0.10
_FORWARD_PATH_PRIOR_STRENGTH = 20.0
_FORWARD_EXEC_PRIOR = 0.50
_FORWARD_EXEC_PRIOR_STRENGTH = 20.0
_FORWARD_TRADE_OUTCOME_PRIOR = 0.50
_FORWARD_TRADE_OUTCOME_PRIOR_STRENGTH = 10.0
_FORWARD_CONFIDENCE_LOW_SAMPLES = 5
_FORWARD_CONFIDENCE_MEDIUM_SAMPLES = 15
_FORWARD_CONFIDENCE_HIGH_SAMPLES = 40


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


def _blend_probabilities(
    historical: float,
    forward: float,
    *,
    history_weight: float = _SCORE_EARN_BLEND_HISTORY_WEIGHT,
    forward_weight: float = _SCORE_EARN_BLEND_FORWARD_WEIGHT,
) -> float:
    h_weight = max(float(history_weight), 0.0)
    f_weight = max(float(forward_weight), 0.0)
    total = h_weight + f_weight
    if total <= 0:
        return _clip01(historical)
    return _clip01((h_weight * float(historical) + f_weight * float(forward)) / total)


def _infer_minute_bars_per_day(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 1
    if "date" in frame.columns:
        day_series = pd.to_datetime(frame["date"], errors="coerce").dt.date
    elif "exec_ts" in frame.columns:
        day_series = pd.to_datetime(frame["exec_ts"], errors="coerce").dt.date
    else:
        return 1
    counts = day_series.value_counts(dropna=True)
    if counts.empty:
        return 1
    median_bars = float(counts.median())
    if not math.isfinite(median_bars):
        return 1
    return max(int(round(median_bars)), 1)


def _infer_unique_days(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    if "date" in frame.columns:
        day_series = pd.to_datetime(frame["date"], errors="coerce").dt.date
    elif "exec_ts" in frame.columns:
        day_series = pd.to_datetime(frame["exec_ts"], errors="coerce").dt.date
    else:
        return 0
    return int(day_series.dropna().nunique())


def _beta_mean(
    *,
    successes: float,
    total: float,
    prior_mean: float,
    prior_strength: float,
) -> float:
    total_value = max(float(total), 0.0)
    strength_value = max(float(prior_strength), 0.0)
    if total_value <= 0 and strength_value <= 0:
        return _clip01(prior_mean)
    alpha = _clip01(prior_mean) * strength_value
    numerator = float(successes) + alpha
    denominator = total_value + strength_value
    if denominator <= 0:
        return _clip01(prior_mean)
    return _clip01(numerator / denominator)


def _dirichlet_three_way_posterior(
    *,
    tp_hits: int,
    sl_hits: int,
    none_hits: int,
    total: int,
    prior_tp: float,
    prior_sl: float,
    prior_strength: float,
) -> tuple[float, float, float]:
    strength_value = max(float(prior_strength), 0.0)
    prior_tp_value = _clip01(prior_tp)
    prior_sl_value = _clip01(prior_sl)
    prior_none_value = max(0.0, 1.0 - prior_tp_value - prior_sl_value)
    prior_total = prior_tp_value + prior_sl_value + prior_none_value
    if prior_total <= 0.0:
        prior_tp_value = 1.0 / 3.0
        prior_sl_value = 1.0 / 3.0
        prior_none_value = 1.0 / 3.0
    else:
        prior_tp_value = prior_tp_value / prior_total
        prior_sl_value = prior_sl_value / prior_total
        prior_none_value = prior_none_value / prior_total

    observed_total = max(int(total), 0)
    denominator = float(observed_total) + strength_value
    if denominator <= 0.0:
        return (
            float(_clip01(prior_tp_value)),
            float(_clip01(prior_sl_value)),
            float(_clip01(prior_none_value)),
        )

    p_tp = (max(int(tp_hits), 0) + prior_tp_value * strength_value) / denominator
    p_sl = (max(int(sl_hits), 0) + prior_sl_value * strength_value) / denominator
    p_none = (max(int(none_hits), 0) + prior_none_value * strength_value) / denominator
    p_tp = _clip01(p_tp)
    p_sl = _clip01(p_sl)
    p_none = _clip01(p_none)
    normalizer = p_tp + p_sl + p_none
    if normalizer <= 0.0:
        return (
            float(_clip01(prior_tp_value)),
            float(_clip01(prior_sl_value)),
            float(_clip01(prior_none_value)),
        )
    return (
        float(_clip01(p_tp / normalizer)),
        float(_clip01(p_sl / normalizer)),
        float(_clip01(p_none / normalizer)),
    )


def _forward_confidence_tier(n_effective: int) -> str:
    sample_size = max(int(n_effective), 0)
    if sample_size >= _FORWARD_CONFIDENCE_HIGH_SAMPLES:
        return "high"
    if sample_size >= _FORWARD_CONFIDENCE_MEDIUM_SAMPLES:
        return "medium"
    if sample_size >= _FORWARD_CONFIDENCE_LOW_SAMPLES:
        return "low"
    return "very_low"


def _select_event_entry_indices(
    frame: pd.DataFrame,
    *,
    horizon_bars: int,
    max_start_exclusive: int,
) -> list[int]:
    if max_start_exclusive <= 0:
        return []

    minimum_spacing = max(int(horizon_bars), 1)
    candidates: list[int] = []

    if not frame.empty and "signal_action" in frame.columns:
        actions = frame["signal_action"].astype(str).str.strip().str.lower()
        candidates.extend(
            int(idx)
            for idx, action in enumerate(actions.tolist())
            if action == "enter" and int(idx) < max_start_exclusive
        )

    if not candidates and not frame.empty and "entry_fill_status" in frame.columns:
        statuses = frame["entry_fill_status"].astype(str).str.strip().str.lower()
        candidates.extend(
            int(idx)
            for idx, status in enumerate(statuses.tolist())
            if status in {"filled", "entry_unfilled", "pending"} and int(idx) < max_start_exclusive
        )

    if not candidates:
        candidates = list(range(0, max_start_exclusive, minimum_spacing))

    selected: list[int] = []
    last_idx = -minimum_spacing
    for idx in sorted(set(candidates)):
        if idx < 0 or idx >= max_start_exclusive:
            continue
        if selected and (idx - last_idx) < minimum_spacing:
            continue
        selected.append(int(idx))
        last_idx = int(idx)
    return selected


def _first_hit_counts_from_entries(
    spread_series: list[float],
    *,
    entry_indices: list[int],
    horizon_bars: int,
    tp: float,
    sl: float,
) -> tuple[int, int, int, int]:
    if not spread_series:
        return 0, 0, 0, 0

    n_values = len(spread_series)
    horizon_value = max(int(horizon_bars), 1)
    tp_value = max(float(tp), 1e-12)
    sl_value = max(float(sl), 1e-12)
    eps = 1e-12

    tp_hits = 0
    sl_hits = 0
    none_hits = 0
    total = 0

    for idx in entry_indices:
        start = int(idx) + 1
        end = int(idx) + horizon_value + 1
        if idx < 0 or end > n_values or start >= end:
            continue
        total += 1
        entry_value = float(spread_series[int(idx)])
        tp_step: int | None = None
        sl_step: int | None = None
        for step_idx, current in enumerate(spread_series[start:end]):
            diff = float(current) - entry_value
            if tp_step is None and diff + eps >= tp_value:
                tp_step = int(step_idx)
            if sl_step is None and diff - eps <= -sl_value:
                sl_step = int(step_idx)
            if tp_step is not None and sl_step is not None:
                break
        if tp_step is None and sl_step is None:
            none_hits += 1
            continue
        if sl_step is None or (tp_step is not None and tp_step < sl_step):
            tp_hits += 1
            continue
        # Tie goes to SL conservatively.
        sl_hits += 1

    return tp_hits, sl_hits, none_hits, total


def _forward_exec_probability_from_entries(frame: pd.DataFrame) -> tuple[float, int]:
    if frame.empty or "entry_fill_status" not in frame.columns:
        return float(_FORWARD_EXEC_PRIOR), 0
    status = frame["entry_fill_status"].astype(str).str.strip().str.lower()
    filled_count = int((status == "filled").sum())
    unfilled_count = int((status == "entry_unfilled").sum())
    total_events = filled_count + unfilled_count
    probability = _beta_mean(
        successes=float(filled_count),
        total=float(total_events),
        prior_mean=_FORWARD_EXEC_PRIOR,
        prior_strength=_FORWARD_EXEC_PRIOR_STRENGTH,
    )
    return float(probability), int(total_events)


def _forward_trade_outcome_probability(frame: pd.DataFrame) -> tuple[float | None, float | None, int]:
    if frame.empty:
        return None, None, 0
    if "trade_return_pct_net" not in frame.columns:
        return None, None, 0
    if "exit_flag" in frame.columns:
        exit_mask = frame["exit_flag"].fillna(False).astype(bool)
    else:
        exit_mask = pd.Series(False, index=frame.index)
    returns = pd.to_numeric(frame.loc[exit_mask, "trade_return_pct_net"], errors="coerce").dropna().astype(float)
    closed = int(returns.size)
    if closed <= 0:
        return None, None, 0
    wins = int((returns > 0.0).sum())
    p_win = _beta_mean(
        successes=float(wins),
        total=float(closed),
        prior_mean=_FORWARD_TRADE_OUTCOME_PRIOR,
        prior_strength=_FORWARD_TRADE_OUTCOME_PRIOR_STRENGTH,
    )
    p_loss = _clip01(1.0 - p_win)
    return float(p_win), float(p_loss), int(closed)


def _build_forward_signal_forecast(
    *,
    frame: pd.DataFrame,
    settings: AppSettings,
    tp_net: float | None,
    as_of_snapshot: date | None,
) -> dict[str, Any]:
    horizon_days = max(int(getattr(settings.spread_carry_alpha, "H_max_days", 20) or 20), 1)
    fallback_date = as_of_snapshot + timedelta(days=horizon_days) if as_of_snapshot is not None else None
    fallback: dict[str, Any] = {
        "forward_tp_probability": 0.0,
        "forward_sl_probability": 0.0,
        "forward_no_exit_probability": 1.0,
        "forward_tp_first_probability": 0.0,
        "forward_sl_first_probability": 0.0,
        "forward_no_exit_first_probability": 1.0,
        "forward_exit_probability": 0.0,
        "forward_earn_probability": 0.0,
        "forward_exec_probability": float(_FORWARD_EXEC_PRIOR),
        "forward_half_life_days": 0.0,
        "forward_effective_days": 0.0,
        "forward_n_effective": 0,
        "forward_confidence_tier": "very_low",
        "forward_entry_events": 0,
        "forward_closed_trades": 0,
        "forecast_exit_days": int(horizon_days),
        "forecast_exit_date": fallback_date.isoformat() if fallback_date is not None else None,
        "forecast_model": "h_max_days",
        "forecast_probability_source": "event_first_hit_shrinkage_v1",
    }
    forward_exec_probability, entry_events = _forward_exec_probability_from_entries(frame)
    fallback["forward_exec_probability"] = float(forward_exec_probability)
    fallback["forward_entry_events"] = int(entry_events)
    _, _, closed_trades = _forward_trade_outcome_probability(frame)
    fallback["forward_closed_trades"] = int(closed_trades)

    if frame.empty or "spread_pct" not in frame.columns:
        return fallback

    spread_series = pd.to_numeric(frame["spread_pct"], errors="coerce").dropna().astype(float).tolist()
    if len(spread_series) < 3:
        return fallback

    bars_per_day = _infer_minute_bars_per_day(frame)
    horizon_bars = max(min(horizon_days * bars_per_day, len(spread_series) - 1), 1)

    tp_cfg = _safe_float(getattr(settings.spread_carry_alpha, "TP_pct", 0.01)) or 0.01
    tp = max(float(tp_net) if tp_net is not None else float(tp_cfg), 1e-6)
    sl_cfg = _safe_float(getattr(settings.spread_carry_alpha, "SL_pct", 0.01)) or 0.01
    sl = max(float(sl_cfg), 1e-6)

    stats = alpha_metrics(
        spread_series,
        horizon=int(horizon_bars),
        tp=tp,
        sl=sl,
    )
    max_start_exclusive = max(len(spread_series) - int(horizon_bars), 0)
    entry_indices = _select_event_entry_indices(
        frame,
        horizon_bars=int(horizon_bars),
        max_start_exclusive=max_start_exclusive,
    )
    tp_hits, sl_hits, none_hits, n_effective = _first_hit_counts_from_entries(
        spread_series,
        entry_indices=entry_indices,
        horizon_bars=int(horizon_bars),
        tp=tp,
        sl=sl,
    )
    p_tp_first, p_sl_first, p_none_first = _dirichlet_three_way_posterior(
        tp_hits=tp_hits,
        sl_hits=sl_hits,
        none_hits=none_hits,
        total=n_effective,
        prior_tp=_FORWARD_PATH_PRIOR_TP,
        prior_sl=_FORWARD_PATH_PRIOR_SL,
        prior_strength=_FORWARD_PATH_PRIOR_STRENGTH,
    )
    p_tp = p_tp_first
    p_sl = p_sl_first
    p_none = p_none_first
    confidence_tier = _forward_confidence_tier(n_effective)
    p_exit = _clip01(p_tp + p_sl)
    p_earn_forward = _clip01(p_tp)

    half_life_bars = _safe_float(stats.half_life) or 0.0
    half_life_days = float(half_life_bars) / float(bars_per_day) if bars_per_day > 0 else float(half_life_bars)
    effective_days = float(n_effective) / float(max(bars_per_day, 1))
    if half_life_days > 0:
        forecast_exit_days = int(round(min(float(horizon_days), max(1.0, float(half_life_days)))))
        forecast_model = "half_life_capped"
    else:
        forecast_exit_days = int(horizon_days)
        forecast_model = "h_max_days"
    forecast_exit_date = (
        (as_of_snapshot + timedelta(days=forecast_exit_days)).isoformat()
        if as_of_snapshot is not None
        else None
    )
    return {
        "forward_tp_probability": float(p_tp),
        "forward_sl_probability": float(p_sl),
        "forward_no_exit_probability": float(p_none),
        "forward_tp_first_probability": float(p_tp_first),
        "forward_sl_first_probability": float(p_sl_first),
        "forward_no_exit_first_probability": float(p_none_first),
        "forward_exit_probability": float(p_exit),
        "forward_earn_probability": float(p_earn_forward),
        "forward_exec_probability": float(forward_exec_probability),
        "forward_half_life_days": float(max(half_life_days, 0.0)),
        "forward_effective_days": float(max(effective_days, 0.0)),
        "forward_n_effective": int(n_effective),
        "forward_confidence_tier": confidence_tier,
        "forward_entry_events": int(entry_events),
        "forward_closed_trades": int(closed_trades),
        "forecast_exit_days": int(forecast_exit_days),
        "forecast_exit_date": forecast_exit_date,
        "forecast_model": forecast_model,
        "forecast_probability_source": "event_first_hit_shrinkage_v1",
    }


def get_last_refresh_telemetry() -> dict[str, Any]:
    with _LAST_REFRESH_TELEMETRY_LOCK:
        telemetry = _LAST_REFRESH_TELEMETRY
    return {
        "incremental_enabled": bool(telemetry.incremental_enabled),
        "data_watermark_before": telemetry.data_watermark_before,
        "data_watermark_after": telemetry.data_watermark_after,
        "pairs_total": int(telemetry.pairs_total),
        "pairs_recomputed": int(telemetry.pairs_recomputed),
        "pairs_reused": int(telemetry.pairs_reused),
        "pairs_skipped": int(telemetry.pairs_skipped),
        "skip_reason": telemetry.skip_reason,
    }


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


def _pair_replay_cache_max(settings: AppSettings) -> int:
    raw = getattr(settings.ui, "unified_pair_replay_cache_max", _PAIR_REPLAY_CACHE_DEFAULT_MAX)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = _PAIR_REPLAY_CACHE_DEFAULT_MAX
    value = max(1, value)
    value = min(value, _PAIR_REPLAY_CACHE_MAX_HARD_LIMIT)
    return value


def _evict_pair_cache_if_needed(max_items: int) -> None:
    if len(_PAIR_REPLAY_CACHE) <= max_items:
        return
    ordered = sorted(_PAIR_REPLAY_CACHE.items(), key=lambda item: item[1].created_at)
    drop = len(_PAIR_REPLAY_CACHE) - max_items
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


def _resolve_incremental_checkpoint_dir(settings: AppSettings, data_dir: Path) -> Path:
    configured = Path(str(getattr(settings.ui, "incremental_checkpoint_dir", "./data/state/incremental_replay")))
    if configured.is_absolute():
        return configured
    text = str(configured).replace("\\", "/")
    if text.startswith("./data/"):
        return data_dir / text[len("./data/") :]
    if text.startswith("data/"):
        return data_dir / text[len("data/") :]
    return data_dir / configured


def _resolve_incremental_output_dir(data_dir: Path) -> Path:
    return data_dir / "output" / "incremental_replay"


def _pair_data_watermark(pair_id: str, ingest_result_map: dict[str, PairIngestResult] | None) -> str | None:
    if not ingest_result_map:
        return None
    item = ingest_result_map.get(pair_id)
    if item is None:
        return None
    return item.after.signature


def _pair_mutation(pair_id: str, ingest_result_map: dict[str, PairIngestResult] | None) -> ReplayMutation:
    if not ingest_result_map or pair_id not in ingest_result_map:
        return ReplayMutation(
            changed=False,
            append_only=True,
            earliest_changed_exec_ts=None,
            watermark_before=None,
            watermark_after=None,
        )
    item = ingest_result_map[pair_id]
    return ReplayMutation(
        changed=bool(item.changed),
        append_only=bool(item.append_only),
        earliest_changed_exec_ts=item.earliest_changed_exec_ts,
        watermark_before=item.before.signature,
        watermark_after=item.after.signature,
    )


def _compute_pair_replay(
    *,
    settings: AppSettings,
    data_dir: Path,
    pair: _UniversePair,
    start_date: date,
    end_date: date,
    key_rates: list[KeyRate],
    force: bool,
    mutation: ReplayMutation,
) -> _PairReplayFetch:
    loaded = load_pair_minute_series(
        data_dir=data_dir,
        stock=pair.stock,
        future=pair.future,
        start_date=start_date,
        end_date=end_date,
    )
    if loaded is None:
        return _PairReplayFetch(
            replay_result=None,
            source=None,
            error="minute_series_not_found",
            cache_hit=False,
            skip_reason=None,
            fallback_reason=None,
            replay_mode="none",
        )
    incremental_enabled = bool(getattr(settings.ui, "incremental_replay_enabled", True))
    replay_result: ReplayResult
    fallback_reason: str | None = None
    skip_reason: str | None = None
    replay_mode = "full"
    if incremental_enabled and not force:
        outcome = run_true_incremental_replay(
            pair_id=pair.pair_id,
            pair=_pair_spec_from_universe(pair),
            series_base=loaded.series_base,
            settings=settings,
            dividends=loaded.dividends,
            key_rates=key_rates,
            mutation=mutation,
            checkpoint_root=_resolve_incremental_checkpoint_dir(settings, data_dir),
            output_root=_resolve_incremental_output_dir(data_dir),
            overlap_minutes=max(int(getattr(settings.ui, "incremental_overlap_minutes", 180) or 0), 1),
            checkpoint_interval_minutes=max(
                int(getattr(settings.ui, "incremental_checkpoint_interval_minutes", 60) or 0),
                1,
            ),
            force_full=False,
        )
        replay_result = outcome.replay_result
        fallback_reason = outcome.fallback_reason
        skip_reason = outcome.skip_reason
        replay_mode = outcome.mode
    else:
        replay_result = run_minute_replay(
            series_base=loaded.series_base,
            pair=_pair_spec_from_universe(pair),
            settings=settings,
            dividends=loaded.dividends,
            key_rates=key_rates,
        )
        replay_mode = "force_full" if force else "full"
    if replay_result.replay.empty:
        return _PairReplayFetch(
            replay_result=replay_result,
            source=loaded.source,
            error="minute_replay_empty",
            cache_hit=False,
            skip_reason=skip_reason,
            fallback_reason=fallback_reason,
            replay_mode=replay_mode,
        )
    return _PairReplayFetch(
        replay_result=replay_result,
        source=loaded.source,
        error=None,
        cache_hit=False,
        skip_reason=skip_reason,
        fallback_reason=fallback_reason,
        replay_mode=replay_mode,
    )


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
    data_watermark: str | None = None,
    mutation: ReplayMutation | None = None,
) -> _PairReplayFetch:
    cache_key = _pair_replay_key(
        settings=settings,
        pair=pair,
        start_date=start_date,
        end_date=end_date,
    )
    mutation_payload = mutation or ReplayMutation(
        changed=False,
        append_only=True,
        earliest_changed_exec_ts=None,
        watermark_before=None,
        watermark_after=data_watermark,
    )
    now = datetime.now(timezone.utc)
    if not force:
        with _PAIR_REPLAY_CACHE_LOCK:
            cached = _PAIR_REPLAY_CACHE.get(cache_key)
            if cached is not None:
                cache_hit = False
                if data_watermark is not None:
                    cache_hit = cached.data_watermark == data_watermark
                else:
                    age = (now - cached.created_at).total_seconds()
                    cache_hit = age <= max(int(ttl_sec), 1)
                if cache_hit:
                    skip_reason = "no_data_change" if not mutation_payload.changed else None
                    return _PairReplayFetch(
                        replay_result=cached.replay_result,
                        source=cached.source,
                        error=None,
                        cache_hit=True,
                        skip_reason=skip_reason,
                        fallback_reason=None,
                        replay_mode="cache",
                    )
    computed = _compute_pair_replay(
        settings=settings,
        data_dir=data_dir,
        pair=pair,
        start_date=start_date,
        end_date=end_date,
        key_rates=key_rates,
        force=force,
        mutation=mutation_payload,
    )
    if computed.replay_result is not None and computed.error is None:
        with _PAIR_REPLAY_CACHE_LOCK:
            _PAIR_REPLAY_CACHE[cache_key] = _PairReplayCacheItem(
                created_at=now,
                replay_result=computed.replay_result,
                source=str(computed.source or ""),
                data_watermark=data_watermark,
            )
            _evict_pair_cache_if_needed(_pair_replay_cache_max(settings))
    return computed


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


def _resolve_entry_tolerance(settings: AppSettings) -> float:
    alpha_cfg = settings.spread_carry_alpha
    raw_value = getattr(alpha_cfg, "entry_price_tolerance_pct", _DEFAULT_ENTRY_PRICE_TOLERANCE_PCT)
    parsed = _safe_float(raw_value)
    if parsed is None:
        parsed = _DEFAULT_ENTRY_PRICE_TOLERANCE_PCT
    return min(max(float(parsed), 0.0001), 0.05)


def _resolve_spread_tolerance(settings: AppSettings) -> float:
    alpha_cfg = settings.spread_carry_alpha
    raw_value = getattr(alpha_cfg, "entry_spread_tolerance_pct", None)
    parsed = _safe_float(raw_value)
    if parsed is None:
        return _resolve_entry_tolerance(settings)
    return min(max(float(parsed), 0.0001), 0.05)


def _entry_plan_from_latest(
    *,
    spot_mid: float | None,
    future_mid: float | None,
    spread_mid: float | None,
    spread_pct: float | None,
    tolerance: float,
    spread_tolerance: float | None = None,
) -> dict[str, float | None]:
    spread_tol = tolerance if spread_tolerance is None else min(max(float(spread_tolerance), 0.0001), 0.05)
    spot = float(spot_mid) if spot_mid is not None else None
    future = float(future_mid) if future_mid is not None else None
    spread_value = float(spread_mid) if spread_mid is not None else None
    spread_pct_value = float(spread_pct) if spread_pct is not None else None
    if spread_value is None and spread_pct_value is not None and spot is not None:
        spread_value = float(spread_pct_value * spot)
    if spread_pct_value is None and spread_value is not None and spot is not None and spot != 0:
        spread_pct_value = float(spread_value / spot)

    spread_band = None
    spread_pct_band = None
    if spread_value is not None:
        spread_band = float(max(abs(spread_value), 1.0) * spread_tol)
        if spot is not None and spot != 0:
            spread_pct_band = float(spread_band / abs(spot))
        elif spread_pct_value is not None:
            spread_pct_band = float(max(abs(spread_pct_value), 0.000001) * spread_tol)

    entry_stock_min = float(spot * (1.0 - tolerance)) if spot is not None and spot > 0 else None
    entry_stock_max = float(spot * (1.0 + tolerance)) if spot is not None and spot > 0 else None
    entry_future_min = float(future * (1.0 - tolerance)) if future is not None and future > 0 else None
    entry_future_max = float(future * (1.0 + tolerance)) if future is not None and future > 0 else None

    entry_spread_min = (
        float(spread_value - spread_band)
        if spread_value is not None and spread_band is not None
        else None
    )
    entry_spread_max = (
        float(spread_value + spread_band)
        if spread_value is not None and spread_band is not None
        else None
    )
    entry_spread_pct_min = (
        float(spread_pct_value - spread_pct_band)
        if spread_pct_value is not None and spread_pct_band is not None
        else None
    )
    entry_spread_pct_max = (
        float(spread_pct_value + spread_pct_band)
        if spread_pct_value is not None and spread_pct_band is not None
        else None
    )
    return {
        "entry_price_tolerance_pct": float(tolerance),
        "entry_spread_tolerance_pct": float(spread_tol),
        "entry_stock_min": entry_stock_min,
        "entry_stock_max": entry_stock_max,
        "entry_future_min_per_share": entry_future_min,
        "entry_future_max_per_share": entry_future_max,
        "entry_spread_min": entry_spread_min,
        "entry_spread_max": entry_spread_max,
        "entry_spread_pct_min": entry_spread_pct_min,
        "entry_spread_pct_max": entry_spread_pct_max,
    }


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
    p_earn_historical = _clip01(p_exec * (share_target_pass or 0.0))
    entry_spread = _safe_float(latest.get("entry_spread_pct_exec"))
    tp_net = _safe_float(latest.get("tp_net"))
    sl_net = _safe_float(latest.get("sl_net"))
    forward_forecast = _build_forward_signal_forecast(
        frame=frame,
        settings=settings,
        tp_net=tp_net,
        as_of_snapshot=latest_date,
    )
    p_exec_forward = _clip01(_safe_float(forward_forecast.get("forward_exec_probability")) or p_exec)
    p_earn_forward_conditional = _clip01(_safe_float(forward_forecast.get("forward_earn_probability")) or 0.0)
    p_earn_forward = _clip01(p_exec_forward * p_earn_forward_conditional)
    p_earn = _blend_probabilities(
        p_earn_historical,
        p_earn_forward,
    )
    score_edge_raw_annual = float(_SCORE_W_FLOOR * score_floor + _SCORE_W_ALPHA * score_alpha)
    signal_score = float(p_exec * score_edge_raw_annual)
    days_observed = int(metrics.days)
    trades_closed = int(metrics.trades_closed)
    score_gate_pass = bool(
        p_exec >= _SCORE_GATE_P_EXEC_THRESHOLD
        and p_earn >= _SCORE_GATE_P_EARN_THRESHOLD
        and signal_score >= _SCORE_GATE_SIGNAL_SCORE_MIN
        and score_floor >= _SCORE_GATE_FLOOR_EXCESS_ANNUAL_MIN
        and days_observed >= _SCORE_GATE_MIN_DAYS
        and trades_closed >= _SCORE_GATE_MIN_CLOSED_TRADES
    )

    spot_mid = _safe_float(latest.get("spot_mid"))
    future_mid = _safe_float(latest.get("future_mid"))
    spread_mid = _safe_float(latest.get("spread_mid"))
    spread_pct = _safe_float(latest.get("spread_pct"))
    entry_tolerance = _resolve_entry_tolerance(settings)
    spread_tolerance = _resolve_spread_tolerance(settings)
    entry_plan = _entry_plan_from_latest(
        spot_mid=spot_mid,
        future_mid=future_mid,
        spread_mid=spread_mid,
        spread_pct=spread_pct,
        tolerance=entry_tolerance,
        spread_tolerance=spread_tolerance,
    )

    tp_spread_level = (
        float(entry_spread + tp_net) if entry_spread is not None and tp_net is not None else None
    )
    sl_spread_level = (
        float(entry_spread - sl_net) if entry_spread is not None and sl_net is not None else None
    )
    signal_metrics = {
        "spot_mid": spot_mid,
        "future_mid": future_mid,
        "spread_mid": spread_mid,
        "spread_pct": spread_pct,
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
        "score_earn_probability_historical": p_earn_historical,
        "score_earn_probability_forward": p_earn_forward,
        "score_earn_probability_forward_conditional": p_earn_forward_conditional,
        "score_exec_probability_forward": p_exec_forward,
        "score_earn_blend_history_weight": float(_SCORE_EARN_BLEND_HISTORY_WEIGHT),
        "score_earn_blend_forward_weight": float(_SCORE_EARN_BLEND_FORWARD_WEIGHT),
        "score_gate_exec_threshold": _SCORE_GATE_P_EXEC_THRESHOLD,
        "score_gate_earn_threshold": _SCORE_GATE_P_EARN_THRESHOLD,
        "score_gate_signal_score_min": _SCORE_GATE_SIGNAL_SCORE_MIN,
        "score_gate_floor_excess_annual_min": _SCORE_GATE_FLOOR_EXCESS_ANNUAL_MIN,
        "score_gate_min_days": _SCORE_GATE_MIN_DAYS,
        "score_gate_min_closed_trades": _SCORE_GATE_MIN_CLOSED_TRADES,
        "score_gate_pass": score_gate_pass,
        "total_score": signal_score,
        "avg_trade_return_annual_recent": _safe_float(metrics.avg_trade_return_annual_fill_to_fill_last5),
        "avg_trade_return_annual_operational_recent": _safe_float(metrics.avg_trade_return_annual_operational_last5),
        "share_target_pass": share_target_pass,
        "unfilled_entry_rate": unfilled_entry_rate,
        "unfilled_exit_rate": unfilled_exit_rate,
        "forced_exit_rate": forced_exit_rate,
        "rows": int(metrics.rows),
        "days": days_observed,
        "entry_signals": int(metrics.entry_signals),
        "exit_signals": int(metrics.exit_signals),
        "trades_closed": trades_closed,
        "avg_entry_wait_min_closed": _safe_float(metrics.avg_entry_wait_min_closed),
        "avg_exit_wait_min_closed": _safe_float(metrics.avg_exit_wait_min_closed),
        **entry_plan,
        "tp_spread_pct_level": tp_spread_level,
        "sl_spread_pct_level": sl_spread_level,
        "forecast_tp_probability": _safe_float(forward_forecast.get("forward_tp_probability")),
        "forecast_sl_probability": _safe_float(forward_forecast.get("forward_sl_probability")),
        "forecast_no_exit_probability": _safe_float(forward_forecast.get("forward_no_exit_probability")),
        "forecast_tp_first_probability": _safe_float(forward_forecast.get("forward_tp_first_probability")),
        "forecast_sl_first_probability": _safe_float(forward_forecast.get("forward_sl_first_probability")),
        "forecast_no_exit_first_probability": _safe_float(
            forward_forecast.get("forward_no_exit_first_probability")
        ),
        "forecast_exit_probability": _safe_float(forward_forecast.get("forward_exit_probability")),
        "forecast_n_effective": _safe_float(forward_forecast.get("forward_n_effective")),
        "forecast_confidence_tier": forward_forecast.get("forward_confidence_tier"),
        "forecast_exit_days": _safe_float(forward_forecast.get("forecast_exit_days")),
        "forecast_exit_date": forward_forecast.get("forecast_exit_date"),
        "forecast_model": forward_forecast.get("forecast_model"),
        "forecast_probability_source": forward_forecast.get("forecast_probability_source"),
        "forward_exec_probability": _safe_float(forward_forecast.get("forward_exec_probability")),
        "forward_entry_events": _safe_float(forward_forecast.get("forward_entry_events")),
        "forward_closed_trades": _safe_float(forward_forecast.get("forward_closed_trades")),
        "forward_effective_days": _safe_float(forward_forecast.get("forward_effective_days")),
        "forward_n_effective": _safe_float(forward_forecast.get("forward_n_effective")),
        "forward_confidence_tier": forward_forecast.get("forward_confidence_tier"),
        "forward_half_life_days": _safe_float(forward_forecast.get("forward_half_life_days")),
        "source": source,
    }
    decision = "ENTER_OK" if signal_action == "enter" else ("EXIT" if signal_action == "exit" else "HOLD")
    reasons = [f"replay_{signal_action}"]
    if int(metrics.trades_closed) <= 0:
        reasons.append("no_closed_trades_in_window")
    if metrics.unfilled_entry_rate is not None and float(metrics.unfilled_entry_rate) >= 1.0:
        reasons.append("entries_unfilled")
    if metrics.error:
        reasons.append(metrics.error)

    top_row: dict[str, Any] = {
        "stock": pair.stock,
        "stock_name": pair.stock_name,
        "future": pair.future,
        "expiry": pair.expiry.isoformat(),
        "spot": spot_mid,
        "future_price": future_mid,
        "spread_mid": spread_mid,
        "spread_pct": spread_pct,
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
        "score_earn_probability_historical": p_earn_historical,
        "score_earn_probability_forward": p_earn_forward,
        "score_earn_probability_forward_conditional": p_earn_forward_conditional,
        "score_exec_probability_forward": p_exec_forward,
        "score_earn_blend_history_weight": float(_SCORE_EARN_BLEND_HISTORY_WEIGHT),
        "score_earn_blend_forward_weight": float(_SCORE_EARN_BLEND_FORWARD_WEIGHT),
        "score_gate_exec_threshold": _SCORE_GATE_P_EXEC_THRESHOLD,
        "score_gate_earn_threshold": _SCORE_GATE_P_EARN_THRESHOLD,
        "score_gate_signal_score_min": _SCORE_GATE_SIGNAL_SCORE_MIN,
        "score_gate_floor_excess_annual_min": _SCORE_GATE_FLOOR_EXCESS_ANNUAL_MIN,
        "score_gate_min_days": _SCORE_GATE_MIN_DAYS,
        "score_gate_min_closed_trades": _SCORE_GATE_MIN_CLOSED_TRADES,
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
        **entry_plan,
        "tp_spread_pct_level": tp_spread_level,
        "sl_spread_pct_level": sl_spread_level,
        "forecast_tp_probability": _safe_float(forward_forecast.get("forward_tp_probability")),
        "forecast_sl_probability": _safe_float(forward_forecast.get("forward_sl_probability")),
        "forecast_no_exit_probability": _safe_float(forward_forecast.get("forward_no_exit_probability")),
        "forecast_tp_first_probability": _safe_float(forward_forecast.get("forward_tp_first_probability")),
        "forecast_sl_first_probability": _safe_float(forward_forecast.get("forward_sl_first_probability")),
        "forecast_no_exit_first_probability": _safe_float(
            forward_forecast.get("forward_no_exit_first_probability")
        ),
        "forecast_exit_probability": _safe_float(forward_forecast.get("forward_exit_probability")),
        "forecast_n_effective": _safe_float(forward_forecast.get("forward_n_effective")),
        "forecast_confidence_tier": forward_forecast.get("forward_confidence_tier"),
        "forecast_exit_days": _safe_float(forward_forecast.get("forecast_exit_days")),
        "forecast_exit_date": forward_forecast.get("forecast_exit_date"),
        "forecast_model": forward_forecast.get("forecast_model"),
        "forecast_probability_source": forward_forecast.get("forecast_probability_source"),
        "forward_exec_probability": _safe_float(forward_forecast.get("forward_exec_probability")),
        "forward_entry_events": _safe_float(forward_forecast.get("forward_entry_events")),
        "forward_closed_trades": _safe_float(forward_forecast.get("forward_closed_trades")),
        "forward_effective_days": _safe_float(forward_forecast.get("forward_effective_days")),
        "forward_n_effective": _safe_float(forward_forecast.get("forward_n_effective")),
        "forward_confidence_tier": forward_forecast.get("forward_confidence_tier"),
        "forward_half_life_days": _safe_float(forward_forecast.get("forward_half_life_days")),
        "avg_trade_return_annual_recent": _safe_float(metrics.avg_trade_return_annual_fill_to_fill_last5),
        "avg_trade_return_annual_operational_recent": _safe_float(metrics.avg_trade_return_annual_operational_last5),
        "share_target_pass": share_target_pass,
        "unfilled_entry_rate": unfilled_entry_rate,
        "unfilled_exit_rate": unfilled_exit_rate,
        "forced_exit_rate": forced_exit_rate,
        "rows": int(metrics.rows),
        "days": days_observed,
        "entry_signals": int(metrics.entry_signals),
        "exit_signals": int(metrics.exit_signals),
        "trades_closed": trades_closed,
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
        "score_earn_probability_historical": p_earn_historical,
        "score_earn_probability_forward": p_earn_forward,
        "score_earn_probability_forward_conditional": p_earn_forward_conditional,
        "score_exec_probability_forward": p_exec_forward,
        "score_earn_blend_history_weight": float(_SCORE_EARN_BLEND_HISTORY_WEIGHT),
        "score_earn_blend_forward_weight": float(_SCORE_EARN_BLEND_FORWARD_WEIGHT),
        "score_gate_exec_threshold": _SCORE_GATE_P_EXEC_THRESHOLD,
        "score_gate_earn_threshold": _SCORE_GATE_P_EARN_THRESHOLD,
        "score_gate_signal_score_min": _SCORE_GATE_SIGNAL_SCORE_MIN,
        "score_gate_floor_excess_annual_min": _SCORE_GATE_FLOOR_EXCESS_ANNUAL_MIN,
        "score_gate_min_days": _SCORE_GATE_MIN_DAYS,
        "score_gate_min_closed_trades": _SCORE_GATE_MIN_CLOSED_TRADES,
        "score_gate_pass": score_gate_pass,
        "total_score": signal_score,
        "spot_mid": spot_mid,
        "future_mid": future_mid,
        "spread_mid": spread_mid,
        "spread_pct": spread_pct,
        "floor_rate_annual": floor_rate_annual,
        **entry_plan,
        "tp_spread_pct_level": tp_spread_level,
        "sl_spread_pct_level": sl_spread_level,
        "forecast_tp_probability": _safe_float(forward_forecast.get("forward_tp_probability")),
        "forecast_sl_probability": _safe_float(forward_forecast.get("forward_sl_probability")),
        "forecast_no_exit_probability": _safe_float(forward_forecast.get("forward_no_exit_probability")),
        "forecast_tp_first_probability": _safe_float(forward_forecast.get("forward_tp_first_probability")),
        "forecast_sl_first_probability": _safe_float(forward_forecast.get("forward_sl_first_probability")),
        "forecast_no_exit_first_probability": _safe_float(
            forward_forecast.get("forward_no_exit_first_probability")
        ),
        "forecast_exit_probability": _safe_float(forward_forecast.get("forward_exit_probability")),
        "forecast_n_effective": _safe_float(forward_forecast.get("forward_n_effective")),
        "forecast_confidence_tier": forward_forecast.get("forward_confidence_tier"),
        "forecast_exit_days": _safe_float(forward_forecast.get("forecast_exit_days")),
        "forecast_exit_date": forward_forecast.get("forecast_exit_date"),
        "forecast_model": forward_forecast.get("forecast_model"),
        "forecast_probability_source": forward_forecast.get("forecast_probability_source"),
        "forward_exec_probability": _safe_float(forward_forecast.get("forward_exec_probability")),
        "forward_entry_events": _safe_float(forward_forecast.get("forward_entry_events")),
        "forward_closed_trades": _safe_float(forward_forecast.get("forward_closed_trades")),
        "forward_effective_days": _safe_float(forward_forecast.get("forward_effective_days")),
        "forward_n_effective": _safe_float(forward_forecast.get("forward_n_effective")),
        "forward_confidence_tier": forward_forecast.get("forward_confidence_tier"),
        "forward_half_life_days": _safe_float(forward_forecast.get("forward_half_life_days")),
        "tp_net": tp_net,
        "sl_net": sl_net,
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


def list_unified_ingest_pairs(
    settings: AppSettings,
    data_dir: Path,
    *,
    as_of: date | None = None,
    max_pairs: int | None = None,
) -> list[IngestPair]:
    as_of_date = as_of or datetime.now(timezone.utc).date()
    universe, _ = _load_universe(settings, data_dir, as_of=as_of_date)
    if max_pairs is not None and max_pairs > 0:
        universe = universe[: max_pairs]
    pairs: list[IngestPair] = []
    for item in universe:
        scale = float(item.lot_size) * float(item.multiplier)
        if scale <= 0:
            scale = 1.0
        pairs.append(
            IngestPair(
                stock=item.stock,
                future=item.future,
                future_scale=scale,
            )
        )
    return pairs


def _build_snapshot_signature(
    *,
    settings: AppSettings,
    data_dir: Path,
    as_of: date,
    lookback_days: int,
    max_pairs: int | None,
    global_data_watermark: str | None = None,
) -> str:
    payload = {
        "settings_sig": _alpha_signature(settings),
        "data_dir": str(data_dir),
        "as_of": as_of.isoformat(),
        "lookback_days": int(lookback_days),
        "max_pairs": int(max_pairs) if max_pairs is not None else None,
        "global_data_watermark": global_data_watermark,
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
    ingest_result_map: dict[str, PairIngestResult] | None = None,
    global_data_watermark_before: str | None = None,
    global_data_watermark_after: str | None = None,
) -> UnifiedMarketSnapshot:
    global _SNAPSHOT_CACHE
    global _LAST_REFRESH_TELEMETRY
    now = datetime.now(timezone.utc)
    as_of_date = as_of or now.date()
    lookback_days = max(int(settings.data.compute_lookback_days or 120), 1)
    signature = _build_snapshot_signature(
        settings=settings,
        data_dir=data_dir,
        as_of=as_of_date,
        lookback_days=lookback_days,
        max_pairs=max_pairs,
        global_data_watermark=global_data_watermark_after,
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
    replay_telemetry: list[PairReplayTelemetry] = []

    pairs_total = len(universe)
    pairs_recomputed = 0
    pairs_reused = 0
    pairs_skipped = 0

    def _compute(pair: _UniversePair) -> tuple[_UniversePair, _PairReplayFetch]:
        pair_watermark = _pair_data_watermark(pair.pair_id, ingest_result_map)
        mutation = _pair_mutation(pair.pair_id, ingest_result_map)
        fetch = get_pair_replay(
            settings=settings,
            data_dir=data_dir,
            pair=pair,
            start_date=start_date,
            end_date=end_date,
            key_rates=key_rates,
            force=force,
            ttl_sec=ttl_sec,
            data_watermark=pair_watermark,
            mutation=mutation,
        )
        return pair, fetch

    workers = max(int(getattr(settings.ui, "unified_pair_workers", 4) or 0), 1)
    if workers <= 1:
        results = [_compute(pair) for pair in universe]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_compute, universe))

    for pair, fetched in results:
        if fetched.cache_hit or fetched.replay_mode in {"reuse", "cache"}:
            pairs_reused += 1
        elif fetched.error is None:
            pairs_recomputed += 1
        if fetched.skip_reason:
            pairs_skipped += 1
        replay_telemetry.append(
            PairReplayTelemetry(
                pair_id=pair.pair_id,
                cache_source=(
                    "cache"
                    if fetched.cache_hit or fetched.replay_mode in {"reuse", "cache"}
                    else "recomputed"
                ),
                skip_reason=fetched.skip_reason,
                fallback_reason=fetched.fallback_reason,
            )
        )
        if fetched.fallback_reason:
            warnings.append(f"{pair.pair_id}:fallback:{fetched.fallback_reason}")
        if fetched.error:
            errors.append(f"{pair.pair_id}:{fetched.error}")
            continue
        replay_result = fetched.replay_result
        if replay_result is None:
            errors.append(f"{pair.pair_id}:replay_none")
            continue
        top_row, signal_row, backtest_row = _build_pair_rows(
            pair=pair,
            replay=replay_result,
            source=fetched.source,
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
    telemetry_skip_reason: str | None = None
    if pairs_total > 0 and pairs_skipped == pairs_total and pairs_recomputed == 0:
        reasons = sorted({item.skip_reason for item in replay_telemetry if item.skip_reason})
        telemetry_skip_reason = reasons[0] if len(reasons) == 1 else "no_data_change"
    with _LAST_REFRESH_TELEMETRY_LOCK:
        _LAST_REFRESH_TELEMETRY = RefreshTelemetry(
            incremental_enabled=bool(getattr(settings.ui, "incremental_replay_enabled", True)),
            data_watermark_before=global_data_watermark_before,
            data_watermark_after=global_data_watermark_after,
            pairs_total=pairs_total,
            pairs_recomputed=pairs_recomputed,
            pairs_reused=pairs_reused,
            pairs_skipped=pairs_skipped,
            skip_reason=telemetry_skip_reason,
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
    fetched = get_pair_replay(
        settings=settings,
        data_dir=data_dir,
        pair=pair,
        start_date=start_date,
        end_date=end_date,
        key_rates=key_rates,
        force=False,
        ttl_sec=ttl_sec,
    )
    if fetched.error or fetched.replay_result is None:
        return pd.DataFrame()
    frame = fetched.replay_result.replay.copy()
    if frame.empty:
        return frame
    if not full_life:
        min_day = as_of - timedelta(days=max(int(window_days), 1))
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
        frame = frame[frame["date"] >= min_day].copy()
    return frame.reset_index(drop=True)


def persist_snapshot_to_csv(snapshot: UnifiedMarketSnapshot, data_dir: Path) -> None:
    persist_snapshot_to_csv_with_meta(snapshot, data_dir)


def _dataframe_sha256(frame: pd.DataFrame) -> str | None:
    if frame.empty:
        return None
    payload = frame.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def persist_snapshot_to_csv_with_meta(
    snapshot: UnifiedMarketSnapshot,
    data_dir: Path,
    *,
    engine_tag: str = "unified",
) -> dict[str, Any]:
    output_root = data_dir / "output"
    engine_value = str(engine_tag or "unified").strip().lower() or "unified"
    output = output_root / engine_value
    output.mkdir(parents=True, exist_ok=True)

    datasets = {
        "top_pairs": snapshot.top_pairs,
        "signals": snapshot.signals,
        "backtest_summary": snapshot.backtests,
    }
    dataset_meta: dict[str, dict[str, Any]] = {}
    for dataset_name, frame in datasets.items():
        csv_name = f"{dataset_name}.csv"
        target = output / csv_name
        rows = int(len(frame))
        if rows > 0:
            frame.to_csv(target, index=False)
            exists = True
        else:
            if target.exists():
                target.unlink()
            exists = False
        dataset_meta[dataset_name] = {
            "path": csv_name,
            "rows": rows,
            "exists": exists,
            "sha256": _dataframe_sha256(frame),
        }

    created_at = snapshot.created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    metadata = {
        "engine": engine_value,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "snapshot_created_at_utc": created_at,
        "datasets": dataset_meta,
        "warnings_total": int(len(snapshot.warnings)),
        "errors_total": int(len(snapshot.errors)),
    }
    (output / "snapshot_meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return metadata


def resolve_series_date_range(frame: pd.DataFrame) -> tuple[date | None, date | None]:
    return _normalize_series_dates(frame)
