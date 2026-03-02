from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd

from moex_carry.analytics.alpha import round_trip_cost
from moex_carry.analytics.floor import compute_floor_metrics
from moex_carry.analytics.liquidity import days_to_exit, dollar_volume, evaluate_liquidity
from moex_carry.analytics.spread import spread_entry_exec, spread_exit_exec, spread_pct
from moex_carry.analytics.stats import zscore
from moex_carry.analytics.time import days_to_expiry, year_fraction
from moex_carry.config import AppSettings
from moex_carry.costs.engine import fut_fee_per_share, round_trip_fees, stock_fee_per_share
from moex_carry.domain.models import ContractSpec, DividendEvent, KeyRate
from moex_carry.execution.model import build_execution_prices
from moex_carry.strategy.spread_carry_alpha import spread_pnl_pct
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


def _build_key_rate_cache(series_dates: list[date], key_rates: list[KeyRate]) -> dict[date, KeyRate | None]:
    days = sorted(set(series_dates))
    if not days:
        return {}
    if not key_rates:
        return {day: None for day in days}
    sorted_rates = sorted(key_rates, key=lambda rate: rate.date)
    cache: dict[date, KeyRate | None] = {}
    idx = 0
    current: KeyRate | None = None
    total = len(sorted_rates)
    for day in days:
        while idx < total and sorted_rates[idx].date <= day:
            current = sorted_rates[idx]
            idx += 1
        cache[day] = current
    return cache


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


def _apply_spread_carry_signals(
    series_df: pd.DataFrame,
    merged: pd.DataFrame | None,
    dividends: list[DividendEvent],
    key_rates: list[KeyRate],
    settings: AppSettings,
    future_spec: ContractSpec,
    alpha_cfg: object,
) -> pd.DataFrame:
    if series_df.empty:
        return series_df
    series_df = series_df.copy()
    if "exec_ts" in series_df.columns:
        series_df = series_df.sort_values(["date", "exec_ts"]).reset_index(drop=True)
    else:
        series_df = series_df.sort_values("date").reset_index(drop=True)
    if merged is not None and "date" in merged.columns:
        merge_cols = [col for col in ("spot_volume", "future_volume", "exec_ts") if col in merged.columns]
        if merge_cols:
            series_df = series_df.merge(merged[["date", *merge_cols]], on="date", how="left")

    n = len(series_df)
    if n == 0:
        return series_df

    try:
        lag_days = max(int(getattr(alpha_cfg, "signal_exec_lag_days", 1) or 0), 0)
    except (TypeError, ValueError):
        lag_days = 1
    try:
        lag_minutes = max(int(getattr(alpha_cfg, "execution_lag_minutes", 1) or 0), 0)
    except (TypeError, ValueError):
        lag_minutes = 1
    try:
        max_wait_minutes = max(int(getattr(alpha_cfg, "execution_max_wait_minutes", 1440) or 0), 0)
    except (TypeError, ValueError):
        max_wait_minutes = 1440
    try:
        force_exit_penalty_bps = max(float(getattr(alpha_cfg, "force_exit_penalty_bps", 0.0) or 0.0), 0.0)
    except (TypeError, ValueError):
        force_exit_penalty_bps = 0.0
    force_exit_policy = str(getattr(alpha_cfg, "force_exit_policy", "next_anchor") or "next_anchor").lower().strip()
    if force_exit_policy not in {"next_anchor", "market_worse"}:
        force_exit_policy = "next_anchor"
    entry_tolerance = max(float(getattr(alpha_cfg, "entry_price_tolerance_pct", 0.0015) or 0.0015), 0.0)
    entry_stock_tolerance_raw = getattr(alpha_cfg, "entry_stock_tolerance_pct", None)
    entry_future_tolerance_raw = getattr(alpha_cfg, "entry_future_tolerance_pct", None)
    entry_stock_tolerance = max(
        float(entry_stock_tolerance_raw if entry_stock_tolerance_raw is not None else entry_tolerance),
        0.0,
    )
    entry_future_tolerance = max(
        float(entry_future_tolerance_raw if entry_future_tolerance_raw is not None else entry_tolerance),
        0.0,
    )
    sequential_entry_enabled = bool(getattr(alpha_cfg, "sequential_entry_enabled", False))
    sequential_entry_first_leg_raw = str(getattr(alpha_cfg, "sequential_entry_first_leg", "future") or "future")
    sequential_entry_first_leg = (
        sequential_entry_first_leg_raw.strip().lower()
        if sequential_entry_first_leg_raw.strip().lower() in {"stock", "future"}
        else "future"
    )
    sequential_entry_second_leg_wait = max(
        int(getattr(alpha_cfg, "sequential_entry_second_leg_max_wait_minutes", 5) or 0),
        0,
    )
    sequential_entry_unwind_penalty_bps = max(
        float(getattr(alpha_cfg, "sequential_entry_unwind_penalty_bps", 0.0) or 0.0),
        0.0,
    )
    sequential_exit_enabled = bool(getattr(alpha_cfg, "sequential_exit_enabled", False))
    sequential_exit_first_leg_raw = str(getattr(alpha_cfg, "sequential_exit_first_leg", "future") or "future")
    sequential_exit_first_leg = (
        sequential_exit_first_leg_raw.strip().lower()
        if sequential_exit_first_leg_raw.strip().lower() in {"stock", "future"}
        else "future"
    )
    sequential_exit_second_leg_wait = max(
        int(getattr(alpha_cfg, "sequential_exit_second_leg_max_wait_minutes", 5) or 0),
        0,
    )
    sequential_exit_force_penalty_raw = getattr(alpha_cfg, "sequential_exit_force_penalty_bps", None)
    sequential_exit_force_penalty_bps = (
        force_exit_penalty_bps
        if sequential_exit_force_penalty_raw is None
        else max(float(sequential_exit_force_penalty_raw or 0.0), 0.0)
    )
    year_basis = _day_count_basis(alpha_cfg.day_count)
    annual_target_override_raw = getattr(alpha_cfg, "annual_target_threshold", None)
    try:
        annual_target_override = (
            float(annual_target_override_raw)
            if annual_target_override_raw is not None
            else None
        )
    except (TypeError, ValueError):
        annual_target_override = None

    def _opposite_leg(leg: str) -> str:
        return "stock" if leg == "future" else "future"

    def _leg_tolerance(leg: str) -> float:
        return entry_stock_tolerance if leg == "stock" else entry_future_tolerance

    def _leg_band_ok(
        *,
        leg: str,
        target_spot: float,
        target_future: float,
        spot_now: float,
        future_now: float,
    ) -> bool:
        if leg == "stock":
            if target_spot <= 0:
                return False
            band = target_spot * _leg_tolerance("stock")
            return abs(spot_now - target_spot) <= band
        if target_future <= 0:
            return False
        band = target_future * _leg_tolerance("future")
        return abs(future_now - target_future) <= band

    def _entry_leg_exec(*, direction: str, leg: str, exec_prices: object) -> float:
        if leg == "stock":
            return (
                float(exec_prices.stock_sell)
                if direction == "reverse"
                else float(exec_prices.stock_buy)
            )
        return (
            float(exec_prices.fut_buy)
            if direction == "reverse"
            else float(exec_prices.fut_sell)
        )

    def _entry_unwind_leg_exec(
        *,
        direction: str,
        leg: str,
        exec_prices: object,
        penalty: float,
    ) -> float:
        if leg == "stock":
            return (
                float(exec_prices.stock_buy) * (1.0 + penalty)
                if direction == "reverse"
                else float(exec_prices.stock_sell) * (1.0 - penalty)
            )
        return (
            float(exec_prices.fut_sell) * (1.0 - penalty)
            if direction == "reverse"
            else float(exec_prices.fut_buy) * (1.0 + penalty)
        )

    def _exit_leg_exec(
        *,
        direction: str,
        leg: str,
        exec_prices: object,
        penalty: float,
    ) -> float:
        if leg == "stock":
            return (
                float(exec_prices.stock_buy) * (1.0 + penalty)
                if direction == "reverse"
                else float(exec_prices.stock_sell) * (1.0 - penalty)
            )
        return (
            float(exec_prices.fut_sell) * (1.0 - penalty)
            if direction == "reverse"
            else float(exec_prices.fut_buy) * (1.0 + penalty)
        )

    def _leg_fee(*, leg: str, stock_fee: float, fut_fee: float) -> float:
        return float(stock_fee) if leg == "stock" else float(fut_fee)

    parsed_dates = pd.to_datetime(series_df["date"], errors="coerce")
    if parsed_dates.isna().any():
        bad_value = series_df.loc[parsed_dates.isna(), "date"].iloc[0]
        raise ValueError(f"Cannot parse date from value: {bad_value!r}")
    series_dates = parsed_dates.dt.date.tolist()

    if "exec_ts" in series_df.columns:
        exec_values = pd.to_datetime(series_df["exec_ts"], errors="coerce", utc=True).dt.tz_convert(None).tolist()
    else:
        exec_values = [None] * n
    series_exec_ts: list[datetime] = []
    for idx, row_date in enumerate(series_dates):
        raw_exec = exec_values[idx]
        if pd.isna(raw_exec):
            series_exec_ts.append(datetime.combine(row_date, datetime.min.time()) + timedelta(hours=23, minutes=59))
            continue
        series_exec_ts.append(raw_exec)

    spot_mid_values = series_df["spot_mid"].to_numpy(dtype=float, copy=False)
    future_mid_values = series_df["future_mid"].to_numpy(dtype=float, copy=False)
    spread_mid_values = series_df["spread_mid"].to_numpy(copy=False) if "spread_mid" in series_df.columns else [0.0] * n
    div_sum_values = series_df["div_sum"].to_numpy(copy=False) if "div_sum" in series_df.columns else [0.0] * n
    pv_div_values = series_df["pv_div"].to_numpy(copy=False) if "pv_div" in series_df.columns else [0.0] * n
    spot_volume_values = series_df["spot_volume"].to_numpy(copy=False) if "spot_volume" in series_df.columns else [None] * n
    future_volume_values = (
        series_df["future_volume"].to_numpy(copy=False) if "future_volume" in series_df.columns else [None] * n
    )
    key_rate_by_day = _build_key_rate_cache(series_dates, key_rates)
    spreads_pct = series_df["spread_pct"].tolist()

    def _submit_timestamp(signal_idx: int, signal_ts: datetime) -> datetime | None:
        if lag_days <= 0:
            return signal_ts + timedelta(minutes=lag_minutes)
        submit_idx = signal_idx + lag_days
        if submit_idx >= n:
            return None
        submit_day = series_dates[submit_idx]
        return datetime.combine(submit_day, datetime.min.time()) + timedelta(minutes=lag_minutes)

    signal_actions: list[str] = ["hold"] * n
    signal_directions: list[str | None] = [None] * n
    entry_flags: list[bool] = [False] * n
    exit_flags: list[bool] = [False] * n
    entry_spread_pcts: list[float | None] = [None] * n
    exit_spread_pcts: list[float | None] = [None] * n
    trade_cycles: list[int | None] = [None] * n
    trade_returns: list[float | None] = [None] * n
    trade_pnls: list[float | None] = [None] * n
    trade_return_pct_net: list[float | None] = [None] * n
    trade_return_annual: list[float | None] = [None] * n
    trade_return_annual_fill_to_fill: list[float | None] = [None] * n
    trade_return_annual_operational: list[float | None] = [None] * n
    annual_target_thresholds: list[float | None] = [None] * n
    annual_target_passes: list[bool | None] = [None] * n
    trade_hold_days: list[int | None] = [None] * n

    entry_signal_days: list[str | None] = [None] * n
    entry_submit_tss: list[str | None] = [None] * n
    entry_fill_tss: list[str | None] = [None] * n
    entry_wait_minutes: list[float | None] = [None] * n
    exit_signal_days: list[str | None] = [None] * n
    exit_submit_tss: list[str | None] = [None] * n
    exit_fill_tss: list[str | None] = [None] * n
    exit_wait_minutes: list[float | None] = [None] * n
    entry_fill_statuses: list[str | None] = [None] * n
    exit_fill_statuses: list[str | None] = [None] * n
    exit_forced_flags: list[bool | None] = [None] * n
    unfilled_reasons: list[str | None] = [None] * n

    rtc_pcts: list[float] = [0.0] * n
    tp_nets: list[float] = [0.0] * n
    sl_nets: list[float] = [0.0] * n
    floor_rates: list[float] = [0.0] * n
    floor_passes: list[bool] = [False] * n
    liquidity_passes: list[bool] = [False] * n
    zscores: list[float] = [0.0] * n

    pending_entry: dict[str, object] | None = None
    pending_exit: dict[str, object] | None = None
    open_position: dict[str, object] | None = None
    current_cycle = 0

    for idx in range(n):
        row_date = series_dates[idx]
        row_ts = series_exec_ts[idx]
        spot_mid = float(spot_mid_values[idx])
        future_mid = float(future_mid_values[idx])
        spread_mid_value = float(spread_mid_values[idx])
        div_sum_value = float(div_sum_values[idx])
        pv_div_value = float(pv_div_values[idx])
        spot_volume = spot_volume_values[idx]
        fut_volume = future_volume_values[idx]

        key_rate_row = key_rate_by_day.get(row_date)
        key_rate_value = key_rate_row.rate if key_rate_row else 0.0
        r_cb = alpha_cfg.r_cb_annual if alpha_cfg.r_cb_annual is not None else key_rate_value
        r_fund = alpha_cfg.r_fund_annual if alpha_cfg.r_fund_annual is not None else r_cb
        dte = days_to_expiry(row_date, future_spec.expiry, alpha_cfg.use_trading_days)
        tau = year_fraction(row_date, future_spec.expiry, alpha_cfg.day_count)

        exec_prices = build_execution_prices(
            stock_bid=None,
            stock_ask=None,
            fut_bid=None,
            fut_ask=None,
            stock_mid=spot_mid,
            fut_mid=future_mid,
            slip_stock_bps=alpha_cfg.slip_stock_bps,
            slip_fut_bps=alpha_cfg.slip_fut_bps,
            slip_fut_ticks=alpha_cfg.slip_fut_ticks,
            tick_size_fut=alpha_cfg.tick_size_fut or future_spec.price_step,
        )
        fee_stock_bps = (
            alpha_cfg.fee_stock_bps
            if alpha_cfg.fee_stock_bps is not None
            else settings.costs.stock_commission_bps
        )
        stock_fee = stock_fee_per_share(
            spot_mid,
            fee_per_share=alpha_cfg.fee_stock_per_share,
            fee_bps=fee_stock_bps,
        )
        fut_fee_per_contract = alpha_cfg.fee_fut_per_contract or 0.0
        fut_fee = fut_fee_per_share(fut_fee_per_contract, future_spec.multiplier)
        fees_rt = round_trip_fees(stock_fee, fut_fee)
        rtc = round_trip_cost(
            exec_prices.stock_buy,
            exec_prices.stock_sell,
            exec_prices.fut_buy,
            exec_prices.fut_sell,
            fees_rt,
        )
        rtc_pct = rtc / spot_mid if spot_mid else 0.0
        tp_net = alpha_cfg.TP_pct + rtc_pct
        sl_net = alpha_cfg.SL_pct + rtc_pct

        floor_metrics = compute_floor_metrics(
            spot_buy=exec_prices.stock_buy,
            fut_sell=exec_prices.fut_sell,
            div_sum=div_sum_value,
            fees_rt=fees_rt,
            r_cb_annual=r_cb,
            r_fund_annual=r_fund,
            tau=tau,
            dte=dte,
            floor_tolerance=alpha_cfg.floor_tolerance,
            riskbuffer_floor=alpha_cfg.riskbuffer_floor,
            capital_base_mode=alpha_cfg.capital_base_mode,
            margin_stock_pct=alpha_cfg.margin_stock_pct,
            margin_fut_pct=alpha_cfg.margin_fut_pct,
            var_margin_buffer_pct=alpha_cfg.var_margin_buffer_pct,
        )

        dollar_vol_stock = dollar_volume(spot_mid, spot_volume)
        dollar_vol_fut = dollar_volume(future_mid, fut_volume, future_spec.multiplier)
        if dollar_vol_stock is not None and dollar_vol_fut is not None:
            avg_dollar = min(dollar_vol_stock, dollar_vol_fut)
        else:
            avg_dollar = dollar_vol_stock or dollar_vol_fut
        position_notional = alpha_cfg.capital_allocated_per_trade
        if position_notional is None and alpha_cfg.max_contracts_per_pair > 0:
            position_notional = spot_mid * future_spec.multiplier * alpha_cfg.max_contracts_per_pair
        days_exit = days_to_exit(position_notional, avg_dollar, alpha_cfg.participation_rate)
        liquidity_pass = evaluate_liquidity(
            spread_bps_stock_value=None,
            spread_bps_fut_value=None,
            dollar_vol_stock_value=dollar_vol_stock,
            dollar_vol_fut_value=dollar_vol_fut,
            open_interest=None,
            days_to_exit_value=days_exit,
            max_spread_bps_stock=alpha_cfg.max_spread_bps_stock,
            max_spread_bps_fut=alpha_cfg.max_spread_bps_fut,
            min_dollar_vol_stock=alpha_cfg.min_avg_dollarvol_stock,
            min_dollar_vol_fut=alpha_cfg.min_avg_dollarvol_fut,
            min_open_interest=alpha_cfg.min_open_interest,
            max_days_to_exit=alpha_cfg.max_days_to_exit,
        )

        z = 0.0
        entry_filter_ok = True
        if alpha_cfg.z_entry_threshold is not None:
            z = zscore(spreads_pct[: idx + 1], window=alpha_cfg.z_window, min_window=10)
            entry_filter_ok = z <= alpha_cfg.z_entry_threshold

        spread_entry_exec_value = spread_entry_exec(
            exec_prices.stock_buy, pv_div_value, exec_prices.fut_sell
        )
        spread_exit_exec_value = spread_exit_exec(
            exec_prices.stock_sell, pv_div_value, exec_prices.fut_buy
        )
        spread_pct_entry_exec = spread_pct(spread_entry_exec_value, spot_mid)
        spread_pct_exit_exec = spread_pct(spread_exit_exec_value, spot_mid)

        rtc_pcts[idx] = rtc_pct
        tp_nets[idx] = tp_net
        sl_nets[idx] = sl_net
        floor_rates[idx] = floor_metrics.floor_rate_annual
        floor_passes[idx] = floor_metrics.floor_pass
        liquidity_passes[idx] = liquidity_pass
        zscores[idx] = z

        if pending_entry is not None:
            signal_idx = int(pending_entry["signal_index"])
            submit_ts = pending_entry["submit_ts"]
            deadline_ts = pending_entry["deadline_ts"]
            if isinstance(submit_ts, datetime) and isinstance(deadline_ts, datetime):
                target_spot = float(pending_entry["target_spot"])
                target_future = float(pending_entry["target_future"])
                target_spread = float(pending_entry["target_spread"])
                direction = str(pending_entry.get("direction", "cash_and_carry"))
                sequential_entry = bool(pending_entry.get("sequential_enabled"))
                if row_ts >= submit_ts and not sequential_entry:
                    if row_ts > deadline_ts:
                        entry_fill_statuses[signal_idx] = "entry_unfilled"
                        unfilled_reasons[signal_idx] = "entry_timeout"
                        pending_entry = None
                    elif _execution_band_ok(
                        target_spot=target_spot,
                        target_future=target_future,
                        target_spread=target_spread,
                        spot_now=spot_mid,
                        future_now=future_mid,
                        spread_now=spread_mid_value,
                        tolerance=entry_tolerance,
                    ):
                        if direction == "reverse":
                            entry_spot_exec = float(exec_prices.stock_sell)
                            entry_fut_exec = float(exec_prices.fut_buy)
                            entry_spread_value = spread_pct_exit_exec
                        else:
                            entry_spot_exec = float(exec_prices.stock_buy)
                            entry_fut_exec = float(exec_prices.fut_sell)
                            entry_spread_value = spread_pct_entry_exec
                        wait_mins = max((row_ts - submit_ts).total_seconds() / 60.0, 0.0)
                        current_cycle += 1
                        open_position = {
                            "cycle_id": current_cycle,
                            "direction": direction,
                            "entry_signal_day": pending_entry["signal_day"],
                            "entry_signal_ts": pending_entry["signal_ts"],
                            "entry_submit_ts": submit_ts,
                            "entry_fill_ts": row_ts,
                            "entry_wait_minutes": wait_mins,
                            "entry_spot_exec": entry_spot_exec,
                            "entry_fut_exec": entry_fut_exec,
                            "entry_spread_pct_exec": entry_spread_value,
                            "entry_stock_fee": float(stock_fee),
                            "entry_fut_fee": float(fut_fee),
                            "r_fund_entry": float(pending_entry["r_fund_entry"]),
                            "annual_target_threshold": (
                                annual_target_override
                                if annual_target_override is not None
                                else float(pending_entry["r_cb_entry"])
                            ),
                        }
                        entry_flags[idx] = True
                        trade_cycles[idx] = current_cycle
                        entry_spread_pcts[idx] = entry_spread_value
                        for target_idx in {signal_idx, idx}:
                            entry_signal_days[target_idx] = str(pending_entry["signal_day"])
                            entry_submit_tss[target_idx] = _iso_or_none(submit_ts)
                            entry_fill_tss[target_idx] = _iso_or_none(row_ts)
                            entry_wait_minutes[target_idx] = wait_mins
                            entry_fill_statuses[target_idx] = "filled"
                        pending_entry = None
                elif row_ts >= submit_ts and sequential_entry:
                    leg_state = str(pending_entry.get("leg_state") or "waiting_first")
                    first_leg = str(pending_entry.get("first_leg") or sequential_entry_first_leg).lower()
                    if first_leg not in {"stock", "future"}:
                        first_leg = "future"
                    second_leg = _opposite_leg(first_leg)
                    if leg_state == "waiting_first":
                        if row_ts > deadline_ts:
                            entry_fill_statuses[signal_idx] = "entry_unfilled"
                            unfilled_reasons[signal_idx] = "entry_timeout"
                            pending_entry = None
                        elif _leg_band_ok(
                            leg=first_leg,
                            target_spot=target_spot,
                            target_future=target_future,
                            spot_now=spot_mid,
                            future_now=future_mid,
                        ):
                            first_exec = _entry_leg_exec(
                                direction=direction,
                                leg=first_leg,
                                exec_prices=exec_prices,
                            )
                            first_fee = _leg_fee(
                                leg=first_leg,
                                stock_fee=float(stock_fee),
                                fut_fee=float(fut_fee),
                            )
                            second_deadline = min(
                                deadline_ts,
                                row_ts + timedelta(minutes=int(pending_entry.get("second_leg_max_wait_minutes") or 0)),
                            )
                            pending_entry["leg_state"] = "waiting_second"
                            pending_entry["first_leg"] = first_leg
                            pending_entry["first_leg_exec"] = first_exec
                            pending_entry["first_leg_fee"] = first_fee
                            pending_entry["first_leg_fill_ts"] = row_ts
                            pending_entry["second_leg_deadline_ts"] = second_deadline
                            leg_state = "waiting_second"
                    if pending_entry is not None and leg_state == "waiting_second":
                        second_deadline_ts = pending_entry.get("second_leg_deadline_ts")
                        if not isinstance(second_deadline_ts, datetime):
                            second_deadline_ts = deadline_ts
                        if row_ts > second_deadline_ts:
                            _entry_unwind_leg_exec(
                                direction=direction,
                                leg=first_leg,
                                exec_prices=exec_prices,
                                penalty=sequential_entry_unwind_penalty_bps / 10000.0,
                            )
                            entry_fill_statuses[signal_idx] = "entry_unfilled"
                            unfilled_reasons[signal_idx] = "entry_second_leg_timeout_unwound"
                            pending_entry = None
                        elif _leg_band_ok(
                            leg=second_leg,
                            target_spot=target_spot,
                            target_future=target_future,
                            spot_now=spot_mid,
                            future_now=future_mid,
                        ):
                            second_exec = _entry_leg_exec(
                                direction=direction,
                                leg=second_leg,
                                exec_prices=exec_prices,
                            )
                            second_fee = _leg_fee(
                                leg=second_leg,
                                stock_fee=float(stock_fee),
                                fut_fee=float(fut_fee),
                            )
                            first_exec = float(pending_entry.get("first_leg_exec") or 0.0)
                            first_fee = float(pending_entry.get("first_leg_fee") or 0.0)
                            if first_leg == "stock":
                                entry_spot_exec = first_exec
                                entry_fut_exec = second_exec
                                entry_stock_fee = first_fee
                                entry_fut_fee = second_fee
                            else:
                                entry_spot_exec = second_exec
                                entry_fut_exec = first_exec
                                entry_stock_fee = second_fee
                                entry_fut_fee = first_fee
                            entry_spread_value = (
                                spread_pct_exit_exec if direction == "reverse" else spread_pct_entry_exec
                            )
                            wait_mins = max((row_ts - submit_ts).total_seconds() / 60.0, 0.0)
                            current_cycle += 1
                            open_position = {
                                "cycle_id": current_cycle,
                                "direction": direction,
                                "entry_signal_day": pending_entry["signal_day"],
                                "entry_signal_ts": pending_entry["signal_ts"],
                                "entry_submit_ts": submit_ts,
                                "entry_fill_ts": row_ts,
                                "entry_wait_minutes": wait_mins,
                                "entry_spot_exec": entry_spot_exec,
                                "entry_fut_exec": entry_fut_exec,
                                "entry_spread_pct_exec": entry_spread_value,
                                "entry_stock_fee": entry_stock_fee,
                                "entry_fut_fee": entry_fut_fee,
                                "r_fund_entry": float(pending_entry["r_fund_entry"]),
                                "annual_target_threshold": (
                                    annual_target_override
                                    if annual_target_override is not None
                                    else float(pending_entry["r_cb_entry"])
                                ),
                            }
                            entry_flags[idx] = True
                            trade_cycles[idx] = current_cycle
                            entry_spread_pcts[idx] = entry_spread_value
                            for target_idx in {signal_idx, idx}:
                                entry_signal_days[target_idx] = str(pending_entry["signal_day"])
                                entry_submit_tss[target_idx] = _iso_or_none(submit_ts)
                                entry_fill_tss[target_idx] = _iso_or_none(row_ts)
                                entry_wait_minutes[target_idx] = wait_mins
                                entry_fill_statuses[target_idx] = "filled"
                            pending_entry = None

        if pending_exit is not None and open_position is not None:
            signal_idx = int(pending_exit["signal_index"])
            submit_ts = pending_exit["submit_ts"]
            deadline_ts = pending_exit["deadline_ts"]
            if isinstance(submit_ts, datetime) and isinstance(deadline_ts, datetime) and row_ts >= submit_ts:
                target_spot = float(pending_exit["target_spot"])
                target_future = float(pending_exit["target_future"])
                target_spread = float(pending_exit["target_spread"])
                direction = str(open_position.get("direction", "cash_and_carry"))
                sequential_exit = bool(pending_exit.get("sequential_enabled"))
                close_now = False
                forced = False
                forced_reason = "exit_timeout_forced"
                exit_spot_exec = 0.0
                exit_fut_exec = 0.0
                exit_stock_fee = float(stock_fee)
                exit_fut_fee = float(fut_fee)

                if not sequential_exit:
                    timed_out = row_ts > deadline_ts
                    band_ok = _execution_band_ok(
                        target_spot=target_spot,
                        target_future=target_future,
                        target_spread=target_spread,
                        spot_now=spot_mid,
                        future_now=future_mid,
                        spread_now=spread_mid_value,
                        tolerance=entry_tolerance,
                    )
                    if band_ok or timed_out:
                        forced = timed_out
                        penalty = (
                            force_exit_penalty_bps / 10000.0
                            if forced and force_exit_policy == "market_worse"
                            else 0.0
                        )
                        exit_spot_exec = _exit_leg_exec(
                            direction=direction,
                            leg="stock",
                            exec_prices=exec_prices,
                            penalty=penalty,
                        )
                        exit_fut_exec = _exit_leg_exec(
                            direction=direction,
                            leg="future",
                            exec_prices=exec_prices,
                            penalty=penalty,
                        )
                        close_now = True
                else:
                    leg_state = str(pending_exit.get("leg_state") or "waiting_first")
                    first_leg = str(pending_exit.get("first_leg") or sequential_exit_first_leg).lower()
                    if first_leg not in {"stock", "future"}:
                        first_leg = "future"
                    second_leg = _opposite_leg(first_leg)
                    if leg_state == "waiting_first":
                        if row_ts > deadline_ts:
                            forced = True
                            penalty = (
                                sequential_exit_force_penalty_bps / 10000.0
                                if force_exit_policy == "market_worse"
                                else 0.0
                            )
                            exit_spot_exec = _exit_leg_exec(
                                direction=direction,
                                leg="stock",
                                exec_prices=exec_prices,
                                penalty=penalty,
                            )
                            exit_fut_exec = _exit_leg_exec(
                                direction=direction,
                                leg="future",
                                exec_prices=exec_prices,
                                penalty=penalty,
                            )
                            close_now = True
                        elif _leg_band_ok(
                            leg=first_leg,
                            target_spot=target_spot,
                            target_future=target_future,
                            spot_now=spot_mid,
                            future_now=future_mid,
                        ):
                            first_exec = _exit_leg_exec(
                                direction=direction,
                                leg=first_leg,
                                exec_prices=exec_prices,
                                penalty=0.0,
                            )
                            first_fee = _leg_fee(
                                leg=first_leg,
                                stock_fee=float(stock_fee),
                                fut_fee=float(fut_fee),
                            )
                            second_deadline = min(
                                deadline_ts,
                                row_ts + timedelta(minutes=int(pending_exit.get("second_leg_max_wait_minutes") or 0)),
                            )
                            pending_exit["leg_state"] = "waiting_second"
                            pending_exit["first_leg"] = first_leg
                            pending_exit["first_leg_exec"] = first_exec
                            pending_exit["first_leg_fee"] = first_fee
                            pending_exit["first_leg_fill_ts"] = row_ts
                            pending_exit["second_leg_deadline_ts"] = second_deadline
                            leg_state = "waiting_second"
                    if pending_exit is not None and leg_state == "waiting_second":
                        second_deadline_ts = pending_exit.get("second_leg_deadline_ts")
                        if not isinstance(second_deadline_ts, datetime):
                            second_deadline_ts = deadline_ts
                        second_forced = row_ts > second_deadline_ts
                        if second_forced or _leg_band_ok(
                            leg=second_leg,
                            target_spot=target_spot,
                            target_future=target_future,
                            spot_now=spot_mid,
                            future_now=future_mid,
                        ):
                            forced = bool(second_forced)
                            if forced:
                                forced_reason = "exit_second_leg_timeout_forced"
                            penalty = (
                                sequential_exit_force_penalty_bps / 10000.0
                                if forced and force_exit_policy == "market_worse"
                                else 0.0
                            )
                            second_exec = _exit_leg_exec(
                                direction=direction,
                                leg=second_leg,
                                exec_prices=exec_prices,
                                penalty=penalty,
                            )
                            second_fee = _leg_fee(
                                leg=second_leg,
                                stock_fee=float(stock_fee),
                                fut_fee=float(fut_fee),
                            )
                            first_exec = float(pending_exit.get("first_leg_exec") or 0.0)
                            first_fee = float(pending_exit.get("first_leg_fee") or 0.0)
                            if first_leg == "stock":
                                exit_spot_exec = first_exec
                                exit_fut_exec = second_exec
                                exit_stock_fee = first_fee
                                exit_fut_fee = second_fee
                            else:
                                exit_spot_exec = second_exec
                                exit_fut_exec = first_exec
                                exit_stock_fee = second_fee
                                exit_fut_fee = first_fee
                            close_now = True

                if close_now:
                    exit_spread_value = spread_pct_entry_exec if direction == "reverse" else spread_pct_exit_exec
                    entry_fill_ts = open_position["entry_fill_ts"]
                    entry_signal_day = open_position["entry_signal_day"]
                    if isinstance(entry_fill_ts, datetime) and isinstance(entry_signal_day, date):
                        entry_date = entry_fill_ts.date()
                        hold_tau = year_fraction(entry_date, row_date, alpha_cfg.day_count)
                        hold_days_value = (row_date - entry_date).days
                        funding_cost = (
                            abs(float(open_position["entry_spot_exec"]))
                            * float(open_position["r_fund_entry"])
                            * hold_tau
                        )
                        dividend_cash = sum(
                            event.amount
                            for event in dividends
                            if entry_date < event.ex_date <= row_date
                        )
                        if direction == "reverse":
                            dividend_cash = -dividend_cash
                            stock_leg = float(open_position["entry_spot_exec"]) - exit_spot_exec
                            fut_leg = exit_fut_exec - float(open_position["entry_fut_exec"])
                        else:
                            stock_leg = exit_spot_exec - float(open_position["entry_spot_exec"])
                            fut_leg = float(open_position["entry_fut_exec"]) - exit_fut_exec

                        fees_total = (
                            float(open_position["entry_stock_fee"])
                            + float(open_position["entry_fut_fee"])
                            + float(exit_stock_fee)
                            + float(exit_fut_fee)
                        )
                        trade_pnl = stock_leg + fut_leg + dividend_cash - funding_cost - fees_total
                        base_spot = abs(float(open_position["entry_spot_exec"]))
                        trade_return_net = trade_pnl / base_spot if base_spot > 0 else None
                        trade_return_spread = spread_pnl_pct(
                            entry_spread_pct_exec=float(open_position["entry_spread_pct_exec"]),
                            exit_spread_pct_exec=exit_spread_value,
                            direction=direction,
                        )
                        trade_return_ann_fill = (
                            trade_return_net / hold_tau
                            if hold_tau > 0 and trade_return_net is not None
                            else None
                        )
                        entry_signal_ts = open_position.get("entry_signal_ts")
                        if isinstance(entry_signal_ts, datetime):
                            operational_start = entry_signal_ts
                        else:
                            operational_start = datetime.combine(entry_signal_day, datetime.min.time())
                        operational_seconds = max((row_ts - operational_start).total_seconds(), 0.0)
                        operational_tau = (
                            operational_seconds / (year_basis * 24.0 * 60.0 * 60.0)
                            if operational_seconds > 0
                            else 0.0
                        )
                        trade_return_ann_oper = (
                            trade_return_net / operational_tau
                            if operational_tau > 0 and trade_return_net is not None
                            else None
                        )
                        annual_threshold = (
                            float(open_position["annual_target_threshold"])
                            if open_position.get("annual_target_threshold") is not None
                            else None
                        )
                        annual_pass = (
                            trade_return_ann_oper >= annual_threshold
                            if trade_return_ann_oper is not None and annual_threshold is not None
                            else None
                        )
                        wait_mins = max((row_ts - submit_ts).total_seconds() / 60.0, 0.0)

                        exit_flags[idx] = True
                        trade_cycles[idx] = int(open_position["cycle_id"])
                        exit_spread_pcts[idx] = exit_spread_value
                        trade_returns[idx] = trade_return_spread
                        trade_pnls[idx] = trade_pnl
                        trade_return_pct_net[idx] = trade_return_net
                        trade_return_annual[idx] = trade_return_ann_fill
                        trade_return_annual_fill_to_fill[idx] = trade_return_ann_fill
                        trade_return_annual_operational[idx] = trade_return_ann_oper
                        annual_target_thresholds[idx] = annual_threshold
                        annual_target_passes[idx] = annual_pass
                        trade_hold_days[idx] = hold_days_value
                        entry_signal_days[idx] = str(entry_signal_day)
                        entry_submit_tss[idx] = _iso_or_none(open_position["entry_submit_ts"])
                        entry_fill_tss[idx] = _iso_or_none(entry_fill_ts)
                        entry_wait_minutes[idx] = float(open_position["entry_wait_minutes"])
                        entry_fill_statuses[idx] = "filled"

                        for target_idx in {signal_idx, idx}:
                            exit_signal_days[target_idx] = str(pending_exit["signal_day"])
                            exit_submit_tss[target_idx] = _iso_or_none(submit_ts)
                            exit_fill_tss[target_idx] = _iso_or_none(row_ts)
                            exit_wait_minutes[target_idx] = wait_mins
                            exit_fill_statuses[target_idx] = "forced" if forced else "filled"
                            exit_forced_flags[target_idx] = forced
                        if forced:
                            unfilled_reasons[signal_idx] = forced_reason
                            unfilled_reasons[idx] = forced_reason

                    pending_exit = None
                    open_position = None

        if pending_entry is not None:
            signal_actions[idx] = "hold"
        elif open_position is None and pending_exit is None:
            can_enter = (
                floor_metrics.floor_pass
                and liquidity_pass
                and entry_filter_ok
                and dte >= alpha_cfg.min_DTE_entry
            )
            if can_enter:
                signal_actions[idx] = "enter"
                signal_directions[idx] = "cash_and_carry"
                entry_signal_days[idx] = row_date.isoformat()
                submit_ts = _submit_timestamp(idx, row_ts)
                if submit_ts is not None:
                    pending_entry = {
                        "signal_index": idx,
                        "signal_day": row_date,
                        "signal_ts": row_ts,
                        "submit_ts": submit_ts,
                        "deadline_ts": submit_ts + timedelta(minutes=max_wait_minutes),
                        "direction": "cash_and_carry",
                        "target_spot": spot_mid,
                        "target_future": future_mid,
                        "target_spread": spread_mid_value,
                        "r_fund_entry": r_fund,
                        "r_cb_entry": r_cb,
                        "sequential_enabled": sequential_entry_enabled,
                        "first_leg": sequential_entry_first_leg,
                        "second_leg_max_wait_minutes": sequential_entry_second_leg_wait,
                        "leg_state": "waiting_first",
                    }
                    entry_submit_tss[idx] = _iso_or_none(submit_ts)
                    entry_fill_statuses[idx] = "pending"
                else:
                    entry_fill_statuses[idx] = "entry_unfilled"
                    unfilled_reasons[idx] = "entry_no_submit_day"
            else:
                signal_actions[idx] = "hold"
        elif open_position is not None and pending_exit is None:
            direction = str(open_position.get("direction", "cash_and_carry"))
            hold_days_value = max((row_date - open_position["entry_fill_ts"].date()).days, 0)
            current_exit_spread = (
                spread_pct_entry_exec if direction == "reverse" else spread_pct_exit_exec
            )
            pnl_spread = spread_pnl_pct(
                entry_spread_pct_exec=float(open_position["entry_spread_pct_exec"]),
                exit_spread_pct_exec=current_exit_spread,
                direction=direction,
            )
            exit_reason = None
            if pnl_spread >= tp_net:
                exit_reason = "tp"
            elif pnl_spread <= -sl_net:
                exit_reason = "sl"
            elif alpha_cfg.H_max_days > 0 and hold_days_value >= alpha_cfg.H_max_days:
                exit_reason = "time"
            elif dte <= alpha_cfg.close_buffer_days:
                exit_reason = "expiry"

            if exit_reason is not None:
                signal_actions[idx] = "exit"
                exit_signal_days[idx] = row_date.isoformat()
                submit_ts = _submit_timestamp(idx, row_ts)
                if submit_ts is not None:
                    pending_exit = {
                        "signal_index": idx,
                        "signal_day": row_date,
                        "signal_ts": row_ts,
                        "submit_ts": submit_ts,
                        "deadline_ts": submit_ts + timedelta(minutes=max_wait_minutes),
                        "target_spot": spot_mid,
                        "target_future": future_mid,
                        "target_spread": spread_mid_value,
                        "reason": exit_reason,
                        "sequential_enabled": sequential_exit_enabled,
                        "first_leg": sequential_exit_first_leg,
                        "second_leg_max_wait_minutes": sequential_exit_second_leg_wait,
                        "leg_state": "waiting_first",
                    }
                    exit_submit_tss[idx] = _iso_or_none(submit_ts)
                    exit_fill_statuses[idx] = "pending"
                else:
                    exit_fill_statuses[idx] = "exit_unfilled"
                    unfilled_reasons[idx] = "exit_no_submit_day"
            else:
                signal_actions[idx] = "hold"
        else:
            signal_actions[idx] = "hold"

    if pending_entry is not None:
        signal_idx = int(pending_entry["signal_index"])
        if entry_fill_statuses[signal_idx] in {None, "pending"}:
            entry_fill_statuses[signal_idx] = "entry_unfilled"
            unfilled_reasons[signal_idx] = unfilled_reasons[signal_idx] or "entry_no_fill_in_window"

    if pending_exit is not None:
        signal_idx = int(pending_exit["signal_index"])
        if exit_fill_statuses[signal_idx] in {None, "pending"}:
            exit_fill_statuses[signal_idx] = "exit_unfilled"
            unfilled_reasons[signal_idx] = unfilled_reasons[signal_idx] or "exit_no_fill_in_window"

    series_df["signal_action"] = signal_actions
    series_df["signal_direction"] = signal_directions
    series_df["entry_flag"] = entry_flags
    series_df["exit_flag"] = exit_flags
    series_df["entry_spread_pct_exec"] = entry_spread_pcts
    series_df["exit_spread_pct_exec"] = exit_spread_pcts
    series_df["trade_cycle"] = trade_cycles
    series_df["trade_return_pct"] = trade_returns
    series_df["trade_pnl_cash"] = trade_pnls
    series_df["trade_return_pct_net"] = trade_return_pct_net
    series_df["trade_return_annual"] = trade_return_annual
    series_df["trade_return_annual_fill_to_fill"] = trade_return_annual_fill_to_fill
    series_df["trade_return_annual_operational"] = trade_return_annual_operational
    series_df["annual_target_threshold"] = annual_target_thresholds
    series_df["annual_target_pass"] = annual_target_passes
    series_df["trade_hold_days"] = trade_hold_days
    series_df["rtc_pct"] = rtc_pcts
    series_df["tp_net"] = tp_nets
    series_df["sl_net"] = sl_nets
    series_df["floor_rate_annual"] = floor_rates
    series_df["floor_pass"] = floor_passes
    series_df["liquidity_pass"] = liquidity_passes
    series_df["zscore"] = zscores
    series_df["entry_signal_day"] = entry_signal_days
    series_df["entry_submit_ts"] = entry_submit_tss
    series_df["entry_fill_ts"] = entry_fill_tss
    series_df["entry_wait_minutes"] = entry_wait_minutes
    series_df["exit_signal_day"] = exit_signal_days
    series_df["exit_submit_ts"] = exit_submit_tss
    series_df["exit_fill_ts"] = exit_fill_tss
    series_df["exit_wait_minutes"] = exit_wait_minutes
    series_df["entry_fill_status"] = entry_fill_statuses
    series_df["exit_fill_status"] = exit_fill_statuses
    series_df["exit_forced"] = exit_forced_flags
    series_df["unfilled_reason"] = unfilled_reasons
    return series_df

def _avg_recent_trade_return_annual(series_df: pd.DataFrame) -> float | None:
    if series_df.empty or "trade_return_annual" not in series_df.columns:
        return None
    exit_mask = (
        series_df["exit_flag"].fillna(False).astype(bool)
        if "exit_flag" in series_df.columns
        else pd.Series(False, index=series_df.index)
    )
    exits = series_df.loc[
        exit_mask & series_df["trade_return_annual"].notna(),
        "trade_return_annual",
    ]
    if exits.empty:
        return None
    return float(exits.tail(RECENT_TRADES_WINDOW).mean())


def _avg_recent_trade_return_annual_operational(series_df: pd.DataFrame) -> float | None:
    if series_df.empty or "trade_return_annual_operational" not in series_df.columns:
        return None
    exit_mask = (
        series_df["exit_flag"].fillna(False).astype(bool)
        if "exit_flag" in series_df.columns
        else pd.Series(False, index=series_df.index)
    )
    exits = series_df.loc[
        exit_mask & series_df["trade_return_annual_operational"].notna(),
        "trade_return_annual_operational",
    ]
    if exits.empty:
        return None
    return float(exits.tail(RECENT_TRADES_WINDOW).mean())

