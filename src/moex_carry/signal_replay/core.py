from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import threading
from typing import Any, Iterator, Mapping

import pandas as pd

from moex_carry.config import AppSettings, CostsConfig, SpreadCarryAlphaConfig
from moex_carry.domain.models import ContractSpec, DividendEvent, KeyRate
from moex_carry.domain.portfolio import PairSpec
import moex_carry.signal_replay.minute_replay as minute_replay_mod
from moex_carry.signal_replay.minute_replay import (
    _apply_spread_carry_signals,
    _avg_recent_trade_return_annual,
    _avg_recent_trade_return_annual_operational,
    _execution_quality_stats,
)

_REPLAY_PATCH_LOCK = threading.Lock()


@dataclass
class ReplayMetrics:
    rows: int
    days: int
    entry_signals: int
    exit_signals: int
    trades_closed: int
    avg_trade_return_annual_fill_to_fill_last5: float | None
    avg_trade_return_annual_operational_last5: float | None
    share_target_pass: float | None
    unfilled_entry_rate: float | None
    unfilled_exit_rate: float | None
    forced_exit_rate: float | None
    avg_entry_wait_min_closed: float | None
    avg_exit_wait_min_closed: float | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "days": self.days,
            "entry_signals": self.entry_signals,
            "exit_signals": self.exit_signals,
            "trades_closed": self.trades_closed,
            "avg_trade_return_annual_fill_to_fill_last5": self.avg_trade_return_annual_fill_to_fill_last5,
            "avg_trade_return_annual_operational_last5": self.avg_trade_return_annual_operational_last5,
            "share_target_pass": self.share_target_pass,
            "unfilled_entry_rate": self.unfilled_entry_rate,
            "unfilled_exit_rate": self.unfilled_exit_rate,
            "forced_exit_rate": self.forced_exit_rate,
            "avg_entry_wait_min_closed": self.avg_entry_wait_min_closed,
            "avg_exit_wait_min_closed": self.avg_exit_wait_min_closed,
            "error": self.error,
        }


@dataclass
class ReplayResult:
    replay: pd.DataFrame
    metrics: ReplayMetrics
    cutoff_minutes: int


def _section(config: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = config.get(key)
    return value if isinstance(value, Mapping) else {}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_replay_settings_from_resolved(resolved_config: Mapping[str, Any]) -> AppSettings:
    execution = _section(resolved_config, "execution")
    rates = _section(resolved_config, "rates")
    costs = _section(resolved_config, "costs")
    liquidity = _section(resolved_config, "liquidity")
    strategy = _section(resolved_config, "strategy")
    portfolio = _section(resolved_config, "portfolio")

    alpha = SpreadCarryAlphaConfig(
        day_count=str(rates.get("day_count") or "ACT/365"),
        use_trading_days=bool(rates.get("use_trading_days") or False),
        price_source=str(execution.get("price_source") or "common_minute_close"),
        common_minute_anchor=str(execution.get("common_minute_anchor") or "last"),
        signal_exec_lag_days=_as_int(strategy.get("signal_exec_lag_days"), 1),
        execution_lag_minutes=_as_int(strategy.get("execution_lag_minutes"), 20),
        execution_max_wait_minutes=_as_int(strategy.get("execution_max_wait_minutes"), 1440),
        force_exit_policy=str(strategy.get("force_exit_policy") or "next_anchor"),
        force_exit_penalty_bps=_as_float(strategy.get("force_exit_penalty_bps"), 0.0),
        annual_target_threshold=_as_float_or_none(strategy.get("annual_target_threshold")),
        r_cb_annual=_as_float_or_none(rates.get("r_cb_annual")),
        r_fund_annual=_as_float_or_none(rates.get("r_fund_annual")),
        r_disc_annual=_as_float_or_none(rates.get("r_disc_annual")),
        price_mode=str(execution.get("price_mode") or "BIDASK"),
        half_spread_bps=_as_float(execution.get("half_spread_bps"), 0.0),
        slip_stock_bps=_as_float(execution.get("slip_stock_bps"), 0.0),
        slip_fut_bps=_as_float(execution.get("slip_fut_bps"), 0.0),
        slip_fut_ticks=_as_float_or_none(execution.get("slip_fut_ticks")),
        tick_size_fut=_as_float_or_none(execution.get("tick_size_fut")),
        fee_stock_per_share=_as_float_or_none(costs.get("fee_stock_per_share")),
        fee_stock_bps=_as_float_or_none(costs.get("fee_stock_bps")),
        fee_fut_per_contract=_as_float_or_none(costs.get("fee_fut_per_contract")),
        floor_tolerance=_as_float(strategy.get("floor_tolerance"), 0.0),
        riskbuffer_floor=_as_float(strategy.get("riskbuffer_floor"), 0.0),
        capital_base_mode=str(strategy.get("capital_base_mode") or "FULL_CASH"),
        margin_stock_pct=_as_float(strategy.get("margin_stock_pct"), 0.0),
        margin_fut_pct=_as_float(strategy.get("margin_fut_pct"), 0.0),
        var_margin_buffer_pct=_as_float(strategy.get("var_margin_buffer_pct"), 0.0),
        max_spread_bps_stock=_as_float_or_none(liquidity.get("max_spread_bps_stock")),
        max_spread_bps_fut=_as_float_or_none(liquidity.get("max_spread_bps_fut")),
        min_avg_dollarvol_stock=_as_float_or_none(liquidity.get("min_avg_dollarvol_stock")),
        min_avg_dollarvol_fut=_as_float_or_none(liquidity.get("min_avg_dollarvol_fut")),
        min_open_interest=_as_float_or_none(liquidity.get("min_open_interest")),
        participation_rate=_as_float(liquidity.get("participation_rate"), 0.1),
        max_days_to_exit=_as_float_or_none(liquidity.get("max_days_to_exit")),
        min_DTE_entry=_as_int(strategy.get("min_DTE_entry"), 7),
        close_buffer_days=_as_int(strategy.get("close_buffer_days"), 3),
        roll_trigger_days=_as_int(strategy.get("roll_trigger_days"), 0),
        H_max_days=_as_int(strategy.get("H_max_days"), 20),
        TP_pct=_as_float(strategy.get("TP_pct"), 0.01),
        SL_pct=_as_float(strategy.get("SL_pct"), 0.01),
        z_window=_as_int(strategy.get("z_window"), 60),
        z_entry_threshold=_as_float_or_none(strategy.get("z_entry_threshold")),
        entry_price_tolerance_pct=_as_float(strategy.get("entry_price_tolerance_pct"), 0.0015),
        entry_stock_tolerance_pct=_as_float_or_none(strategy.get("entry_stock_tolerance_pct")),
        entry_future_tolerance_pct=_as_float_or_none(strategy.get("entry_future_tolerance_pct")),
        entry_spread_tolerance_pct=_as_float_or_none(strategy.get("entry_spread_tolerance_pct")),
        signal_cutoff_before_day_end_minutes=_as_int(strategy.get("signal_cutoff_before_day_end_minutes"), 0),
        max_gross_notional=_as_float_or_none(portfolio.get("max_gross_notional")),
        max_contracts_per_pair=_as_int(portfolio.get("max_contracts_per_pair"), 1),
        capital_allocated_per_trade=_as_float_or_none(portfolio.get("capital_allocated_per_trade")),
        margin_proxy=_as_float(portfolio.get("margin_proxy"), 1.0),
    )
    return AppSettings(
        costs=CostsConfig(
            stock_commission_bps=_as_float(costs.get("stock_commission_bps"), 1.5),
            futures_commission_bps=_as_float(costs.get("futures_commission_bps"), 1.0),
            exchange_fee_bps=_as_float(costs.get("exchange_fee_bps"), 0.5),
            slippage_bps=0.0,
        ),
        spread_carry_alpha=alpha,
    )


def apply_day_cutoff(df: pd.DataFrame, cutoff_minutes: int) -> pd.DataFrame:
    if df.empty or cutoff_minutes <= 0:
        return df.copy()
    if "exec_ts" not in df.columns or "date" not in df.columns:
        return df.copy()
    work = df.copy()
    work["exec_ts"] = pd.to_datetime(work["exec_ts"], errors="coerce")
    work = work.dropna(subset=["exec_ts"])
    if work.empty:
        return work
    day_last = work.groupby("date", as_index=False)["exec_ts"].max().rename(columns={"exec_ts": "day_last_ts"})
    work = work.merge(day_last, on="date", how="left")
    work["keep_until"] = work["day_last_ts"] - pd.to_timedelta(int(cutoff_minutes), unit="m")
    filtered = work[work["exec_ts"] <= work["keep_until"]].copy()
    filtered = filtered.drop(columns=["day_last_ts", "keep_until"])
    return filtered.reset_index(drop=True)


def _normalize_series_base(series: pd.DataFrame) -> pd.DataFrame:
    if series.empty:
        return series.copy()
    work = series.copy()
    rename_map: dict[str, str] = {}
    if "spot_mid" not in work.columns and "spot" in work.columns:
        rename_map["spot"] = "spot_mid"
    if "future_mid" not in work.columns and "future" in work.columns:
        rename_map["future"] = "future_mid"
    if rename_map:
        work = work.rename(columns=rename_map)
    if "date" not in work.columns and "exec_ts" in work.columns:
        work["date"] = pd.to_datetime(work["exec_ts"], errors="coerce").dt.date
    if "exec_ts" not in work.columns:
        work["exec_ts"] = pd.to_datetime(work["date"], errors="coerce")
    if "pv_div" not in work.columns:
        work["pv_div"] = 0.0
    if "div_sum" not in work.columns:
        work["div_sum"] = 0.0
    if "spot_volume" not in work.columns:
        work["spot_volume"] = 0.0
    if "future_volume" not in work.columns:
        work["future_volume"] = 0.0
    if "spread_mid" not in work.columns and {"spot_mid", "future_mid"}.issubset(work.columns):
        work["spread_mid"] = pd.to_numeric(work["spot_mid"], errors="coerce") - pd.to_numeric(
            work["future_mid"], errors="coerce"
        )
    if "spread_pct" not in work.columns and {"spread_mid", "spot_mid"}.issubset(work.columns):
        spot = pd.to_numeric(work["spot_mid"], errors="coerce")
        work["spread_pct"] = pd.to_numeric(work["spread_mid"], errors="coerce") / spot.where(spot != 0)

    required = [
        "date",
        "spot_mid",
        "future_mid",
        "pv_div",
        "div_sum",
        "spread_mid",
        "spread_pct",
        "exec_ts",
        "spot_volume",
        "future_volume",
    ]
    for col in required:
        if col not in work.columns:
            work[col] = 0.0 if col not in {"date", "exec_ts"} else None
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.date
    work["exec_ts"] = pd.to_datetime(work["exec_ts"], errors="coerce")
    work = work.dropna(subset=["date", "exec_ts", "spot_mid", "future_mid"])
    return work[required].reset_index(drop=True)


def _build_split_band_fn(
    *,
    stock_tolerance: float,
    future_tolerance: float,
    spread_tolerance: float,
):
    stock_tol = max(float(stock_tolerance), 0.0)
    future_tol = max(float(future_tolerance), 0.0)
    spread_tol = max(float(spread_tolerance), 0.0)

    def _split_band_ok(
        *,
        target_spot: float,
        target_future: float,
        target_spread: float,
        spot_now: float,
        future_now: float,
        spread_now: float,
        tolerance: float,
    ) -> bool:
        del tolerance
        if target_spot <= 0 or target_future <= 0:
            return False
        stock_band = target_spot * stock_tol
        future_band = target_future * future_tol
        spread_base = max(abs(target_spread), 1.0)
        spread_band = spread_base * spread_tol
        return (
            abs(spot_now - target_spot) <= stock_band
            and abs(future_now - target_future) <= future_band
            and abs(spread_now - target_spread) <= spread_band
        )

    return _split_band_ok


@contextmanager
def _patched_split_tolerance(alpha: SpreadCarryAlphaConfig) -> Iterator[None]:
    fallback = max(float(alpha.entry_price_tolerance_pct or 0.0), 0.0)
    stock_tol = alpha.entry_stock_tolerance_pct
    future_tol = alpha.entry_future_tolerance_pct
    spread_tol = alpha.entry_spread_tolerance_pct
    if stock_tol is None and future_tol is None and spread_tol is None:
        yield
        return
    stock_value = max(float(stock_tol if stock_tol is not None else fallback), 0.0)
    future_value = max(float(future_tol if future_tol is not None else fallback), 0.0)
    spread_value = max(float(spread_tol if spread_tol is not None else fallback), 0.0)
    with _REPLAY_PATCH_LOCK:
        original = minute_replay_mod._execution_band_ok
        minute_replay_mod._execution_band_ok = _build_split_band_fn(
            stock_tolerance=stock_value,
            future_tolerance=future_value,
            spread_tolerance=spread_value,
        )
        try:
            yield
        finally:
            minute_replay_mod._execution_band_ok = original


def _collect_metrics(replay: pd.DataFrame) -> ReplayMetrics:
    action = replay["signal_action"].astype(str).str.lower() if "signal_action" in replay.columns else pd.Series([], dtype="string")
    entry_signals = int((action == "enter").sum())
    exit_signals = int((action == "exit").sum())
    exit_mask = replay["exit_flag"].fillna(False).astype(bool) if "exit_flag" in replay.columns else pd.Series(False, index=replay.index)
    closed_mask = exit_mask & replay["trade_return_annual_operational"].notna()
    trades_closed = int(closed_mask.sum())
    stats = _execution_quality_stats(replay)
    avg_fill = _avg_recent_trade_return_annual(replay)
    avg_oper = _avg_recent_trade_return_annual_operational(replay)
    entry_wait = replay.loc[closed_mask, "entry_wait_minutes"].dropna() if "entry_wait_minutes" in replay.columns else pd.Series(dtype=float)
    exit_wait = replay.loc[closed_mask, "exit_wait_minutes"].dropna() if "exit_wait_minutes" in replay.columns else pd.Series(dtype=float)
    return ReplayMetrics(
        rows=int(len(replay)),
        days=int(pd.Series(replay["date"]).nunique()) if "date" in replay.columns else 0,
        entry_signals=entry_signals,
        exit_signals=exit_signals,
        trades_closed=trades_closed,
        avg_trade_return_annual_fill_to_fill_last5=avg_fill,
        avg_trade_return_annual_operational_last5=avg_oper,
        share_target_pass=stats.get("share_target_pass"),
        unfilled_entry_rate=stats.get("unfilled_entry_rate"),
        unfilled_exit_rate=stats.get("unfilled_exit_rate"),
        forced_exit_rate=stats.get("forced_exit_rate"),
        avg_entry_wait_min_closed=float(entry_wait.mean()) if not entry_wait.empty else None,
        avg_exit_wait_min_closed=float(exit_wait.mean()) if not exit_wait.empty else None,
        error=None,
    )


def run_minute_replay(
    *,
    series_base: pd.DataFrame,
    pair: PairSpec,
    settings: AppSettings,
    dividends: list[DividendEvent],
    key_rates: list[KeyRate],
) -> ReplayResult:
    alpha = settings.spread_carry_alpha
    cutoff_minutes = max(int(getattr(alpha, "signal_cutoff_before_day_end_minutes", 0) or 0), 0)
    normalized = _normalize_series_base(series_base)
    series = apply_day_cutoff(normalized, cutoff_minutes)
    if series.empty:
        return ReplayResult(
            replay=series,
            cutoff_minutes=cutoff_minutes,
            metrics=ReplayMetrics(
                rows=0,
                days=0,
                entry_signals=0,
                exit_signals=0,
                trades_closed=0,
                avg_trade_return_annual_fill_to_fill_last5=None,
                avg_trade_return_annual_operational_last5=None,
                share_target_pass=None,
                unfilled_entry_rate=None,
                unfilled_exit_rate=None,
                forced_exit_rate=None,
                avg_entry_wait_min_closed=None,
                avg_exit_wait_min_closed=None,
                error="series_empty_after_cutoff",
            ),
        )

    expiry = pair.expiry
    if expiry is None:
        expiry = max(series["date"])
    future_spec = ContractSpec(
        secid=pair.future_secid,
        asset_code=pair.stock_secid,
        expiry=expiry,
        lot_size=float(pair.lot_size or 1.0),
        price_step=float(pair.tick_size or 0.01),
        multiplier=float(pair.multiplier or 1.0),
    )
    with _patched_split_tolerance(alpha):
        replay = _apply_spread_carry_signals(
            series,
            merged=None,
            dividends=dividends,
            key_rates=key_rates,
            settings=settings,
            future_spec=future_spec,
            alpha_cfg=alpha,
        )
    metrics = _collect_metrics(replay)
    return ReplayResult(replay=replay, metrics=metrics, cutoff_minutes=cutoff_minutes)
