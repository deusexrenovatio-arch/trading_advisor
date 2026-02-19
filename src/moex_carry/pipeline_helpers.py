from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from moex_carry.config import AppSettings
from moex_carry.costs.engine import CostProfile, total_cost_bps
from moex_carry.domain.decision import RiskProfile
from moex_carry.domain.models import ContractSpec

RECENT_TRADES_WINDOW = 5

def _day_count_basis(day_count: str) -> float:
    raw = str(day_count or "ACT/365").upper()
    return 360.0 if "360" in raw else 365.0
def _as_date(value: object) -> date:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"Cannot parse date from value: {value!r}")
    if isinstance(ts, pd.Timestamp):
        return ts.date()
    if isinstance(ts, datetime):
        return ts.date()
    raise ValueError(f"Unsupported date value: {value!r}")
def _as_naive_datetime(value: object) -> datetime | None:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is not None:
            ts = ts.tz_convert(None)
        return ts.to_pydatetime().replace(tzinfo=None)
    if isinstance(ts, datetime):
        if ts.tzinfo is not None:
            return ts.astimezone(timezone.utc).replace(tzinfo=None)
        return ts
    return None
def _row_exec_timestamp(row_date: date, exec_ts_raw: object) -> datetime:
    parsed = _as_naive_datetime(exec_ts_raw)
    if parsed is not None:
        return parsed
    # In legacy daily-close mode there is no minute anchor, so we pin to end-of-day.
    return datetime.combine(row_date, datetime.min.time()) + timedelta(hours=23, minutes=59)
def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value is not None else None
def _execution_band_ok(
    *,
    target_spot: float,
    target_future: float,
    target_spread: float,
    spot_now: float,
    future_now: float,
    spread_now: float,
    tolerance: float,
) -> bool:
    if target_spot <= 0 or target_future <= 0:
        return False
    tol = max(float(tolerance), 0.0)
    stock_band = target_spot * tol
    future_band = target_future * tol
    spread_band = max(abs(target_spread), 1.0) * tol
    return (
        abs(spot_now - target_spot) <= stock_band
        and abs(future_now - target_future) <= future_band
        and abs(spread_now - target_spread) <= spread_band
    )
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
def _risk_profile_from_settings(settings: AppSettings) -> RiskProfile:
    profile = settings.risk_profile
    return RiskProfile(
        account_equity=profile.account_equity,
        account_currency=profile.account_currency,
        max_risk_per_trade_pct=profile.max_risk_per_trade_pct,
        max_daily_loss_pct=profile.max_daily_loss_pct,
        max_open_risk_pct=profile.max_open_risk_pct,
        max_leverage=profile.max_leverage,
        max_margin_pct=profile.max_margin_pct,
        max_contracts_per_instrument=profile.max_contracts_per_instrument,
        max_positions=profile.max_positions,
        max_correlated_exposure_pct=profile.max_correlated_exposure_pct,
        stop_loss_required=profile.stop_loss_required,
        time_stop_minutes=profile.time_stop_minutes,
        slippage_tolerance_ticks=profile.slippage_tolerance_ticks,
    )
def _build_cost_model(
    cost_profile: CostProfile,
    future_price: float,
    future_spec: ContractSpec | None,
) -> dict[str, float]:
    if future_spec is None:
        return {"fee_side": 0.0, "round_trip_cost": 0.0, "break_even_ticks": 0.0}
    notional = future_price * future_spec.multiplier
    fee_side = (total_cost_bps(cost_profile) / 10000.0) * notional
    round_trip_cost = fee_side * 2
    tick_value = future_spec.price_step * future_spec.multiplier
    break_even_ticks = round_trip_cost / tick_value if tick_value else 0.0
    break_even_points = break_even_ticks * future_spec.price_step
    return {
        "fee_side": fee_side,
        "round_trip_cost": round_trip_cost,
        "break_even_ticks": break_even_ticks,
        "break_even_points": break_even_points,
    }
def _resolve_unified_max_pairs(settings: AppSettings, max_pairs: int | None) -> int | None:
    if max_pairs is not None:
        configured = int(max_pairs)
        return configured if configured > 0 else None
    refresh_max = getattr(settings.ui, "signal_refresh_max_pairs", None)
    if refresh_max is not None:
        configured = int(refresh_max)
        return configured if configured > 0 else None
    return None
def _resolve_incremental_checkpoint_root(settings: AppSettings, data_dir: Path) -> Path:
    configured = Path(str(getattr(settings.ui, "incremental_checkpoint_dir", "./data/state/incremental_replay")))
    if configured.is_absolute():
        return configured
    text = str(configured).replace("\\", "/")
    if text.startswith("./data/"):
        return data_dir / text[len("./data/") :]
    if text.startswith("data/"):
        return data_dir / text[len("data/") :]
    return data_dir / configured
def _reference_data_stale(paths: Iterable[Path], *, max_age_hours: float) -> bool:
    now = datetime.now(timezone.utc)
    max_age_seconds = max(float(max_age_hours), 0.0) * 3600.0
    for path in paths:
        if not path.exists():
            return True
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return True
        if (now - modified).total_seconds() >= max_age_seconds:
            return True
    return False
def _run_unified_incremental_ingest(
    settings: AppSettings,
    *,
    data_dir: Path,
    max_pairs: int | None,
):
    if not bool(getattr(settings.ui, "incremental_replay_enabled", True)):
        return None
    from moex_carry.minute_ingest.runner import run_incremental_minute_ingest
    from moex_carry.unified_runtime import list_unified_ingest_pairs

    ingest_pairs = list_unified_ingest_pairs(
        settings,
        data_dir,
        max_pairs=max_pairs,
    )
    if not ingest_pairs:
        return None
    return run_incremental_minute_ingest(
        settings=settings,
        data_dir=data_dir,
        checkpoint_root=_resolve_incremental_checkpoint_root(settings, data_dir),
        pairs=ingest_pairs,
        overlap_minutes=max(int(getattr(settings.ui, "incremental_overlap_minutes", 180) or 0), 1),
    )
def _build_unified_snapshot(
    *,
    settings: AppSettings,
    data_dir: Path,
    max_pairs: int | None,
    as_of: date | None,
    ingest_cycle=None,
):
    from moex_carry.unified_runtime import build_unified_market_snapshot

    return build_unified_market_snapshot(
        settings,
        data_dir,
        force=False,
        ttl_sec=max(int(getattr(settings.ui, "unified_snapshot_ttl_sec", 120) or 0), 1),
        as_of=as_of,
        max_pairs=max_pairs,
        ingest_result_map=(ingest_cycle.pair_results if ingest_cycle is not None else None),
        global_data_watermark_before=(
            ingest_cycle.global_watermark_before if ingest_cycle is not None else None
        ),
        global_data_watermark_after=(
            ingest_cycle.global_watermark_after if ingest_cycle is not None else None
        ),
    )
