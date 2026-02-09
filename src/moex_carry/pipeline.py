from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from moex_carry.analytics.alpha import alpha_metrics, round_trip_cost
from moex_carry.analytics.dividends import div_sum, pv_dividends_exp
from moex_carry.analytics.floor import compute_floor_metrics
from moex_carry.analytics.liquidity import (
    days_to_exit,
    dollar_volume,
    evaluate_liquidity,
    spread_bps,
)
from moex_carry.analytics.spread import (
    spread_entry_exec,
    spread_exit_exec,
    spread_mid,
    spread_pct,
)
from moex_carry.analytics.stats import zscore
from moex_carry.analytics.time import days_to_expiry, year_fraction
from moex_carry.config import AppSettings, resolve_paths
from moex_carry.costs.engine import (
    CostProfile,
    fut_fee_per_share,
    round_trip_fees,
    stock_fee_per_share,
    total_cost_bps,
)
from moex_carry.costs.taxes import TaxProfile
from moex_carry.data import CbrKeyRateClient, MoexIssClient, build_fut_point, build_stock_point
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.data.dividends import apply_overrides, load_dividends
from moex_carry.decision_log import DecisionLogStore, build_decision_view, build_snapshot
from moex_carry.domain.decision import NewsItem, RiskProfile
from moex_carry.domain.models import ContractSpec, DividendEvent, Instrument, KeyRate
from moex_carry.execution.model import build_execution_prices
from moex_carry.selection.ranking import score_pairs_alpha
from moex_carry.selection.universe import build_pair_mappings
from moex_carry.strategy.news_filter import apply_news_filter
from moex_carry.strategy.overall_strategy import aggregate_strategy_signals, strategy_signal_to_dict
from moex_carry.strategy.orchestrator import build_portfolio_proposal
from moex_carry.strategy.risk_gate import evaluate_risk_profile
from moex_carry.strategy.spread_carry_alpha import SpreadCarryState, step_spread_carry_alpha
from moex_carry.strategy.spread_adapter import load_spread_signals
from moex_carry.backtest.engine import BacktestResult, backtest_pair
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    delete_signal_history_run,
    store_signal_history,
    store_signal_run,
)


def _data_paths(base_dir: Path) -> dict[str, Path]:
    raw_dir = base_dir / "raw"
    output_dir = base_dir / "output"
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return {"raw": raw_dir, "output": output_dir}


def fetch_data(settings: AppSettings, max_shares: int | None = None) -> None:
    paths = resolve_paths(settings)
    dirs = _data_paths(paths.data_dir)

    client = MoexIssClient(settings.moex.base_url, settings.moex.request_timeout_sec)
    print("[fetch] Downloading MOEX shares list...", flush=True)
    shares: list[dict[str, object]] = []
    limit = max_shares if max_shares and max_shares > 0 else None
    for idx, item in enumerate(
        client.iter_securities(
            settings.moex.engine_shares,
            settings.moex.market_shares,
            settings.moex.shares_board,
        ),
        start=1,
    ):
        shares.append(item)
        if limit is not None and len(shares) >= limit:
            print(f"[fetch] Reached max_shares={limit}, stopping.", flush=True)
            break
        if idx % 200 == 0:
            print(f"[fetch] Shares loaded: {idx}", flush=True)
    print(f"[fetch] Shares total: {len(shares)}", flush=True)
    futures = client.get_futures_specs(settings.moex.futures_board)
    print(f"[fetch] Futures total: {len(futures)}", flush=True)
    pd.DataFrame(shares).to_csv(dirs["raw"] / "shares.csv", index=False)
    pd.DataFrame(futures).to_csv(dirs["raw"] / "futures.csv", index=False)

    cbr_client = CbrKeyRateClient(
        settings.cbr.base_url, settings.cbr.key_rate_path, settings.moex.request_timeout_sec
    )
    print("[fetch] Downloading CBR key rate history...", flush=True)
    rates = cbr_client.get_key_rate_history()
    print(f"[fetch] Key rates: {len(rates)} rows", flush=True)
    pd.DataFrame([{"date": r.date, "rate": r.rate} for r in rates]).to_csv(
        dirs["raw"] / "key_rates.csv", index=False
    )


def _parse_contract_specs(futures_df: pd.DataFrame) -> list[ContractSpec]:
    specs = []
    for _, row in futures_df.iterrows():
        if not row.get("SECID") or not row.get("ASSETCODE"):
            continue
        expiry_raw = row.get("LASTTRADEDATE") or row.get("LASTTRADINGDAY")
        expiry = pd.to_datetime(expiry_raw).date() if expiry_raw else None
        if not expiry:
            continue
        lot_raw = row.get("LOTVOLUME") or row.get("LOTSIZE") or row.get("LOT") or 1
        multiplier_raw = row.get("MULTIPLIER") or 1
        specs.append(
            ContractSpec(
                secid=row["SECID"],
                asset_code=row["ASSETCODE"],
                expiry=expiry,
                lot_size=float(lot_raw),
                price_step=float(row.get("MINSTEP", 1)),
                multiplier=float(multiplier_raw),
            )
        )
    return specs


def _parse_instruments(shares_df: pd.DataFrame) -> list[Instrument]:
    instruments = []
    for _, row in shares_df.iterrows():
        if not row.get("SECID"):
            continue
        instruments.append(
            Instrument(
                secid=row["SECID"],
                name=row.get("SHORTNAME") or row.get("SECNAME") or row["SECID"],
                instrument_type="stock",
                currency=row.get("CURRENCYID", "RUB"),
                board=row.get("BOARDID"),
            )
        )
    return instruments


def _load_key_rates(path: Path) -> list[KeyRate]:
    if not path.exists():
        return []
    df = pd.read_csv(path)
    return [KeyRate(date=pd.to_datetime(row["date"]).date(), rate=float(row["rate"])) for _, row in df.iterrows()]


def _load_dividends(client: MoexIssClient, stock: str, data_dir: Path) -> list[DividendEvent]:
    events = load_dividends(client, stock)
    overrides_path = data_dir / "dividends_overrides.csv"
    return apply_overrides(events, overrides_path)


def _fetch_candles(
    client: MoexIssClient,
    engine: str,
    market: str,
    board: str,
    secid: str,
    from_date: date,
    till_date: date,
    price_scale: float = 1.0,
) -> pd.DataFrame:
    raw = client.get_candles(engine, market, secid, board, from_date, till_date, interval=24)
    df = pd.DataFrame(raw)
    if df.empty:
        return df
    if price_scale and price_scale != 1.0:
        df["close"] = pd.to_numeric(df["close"], errors="coerce") / price_scale
    df["date"] = pd.to_datetime(df["begin"]).dt.date
    df.rename(columns={"close": secid, "volume": f"{secid}_volume"}, inplace=True)
    return df[["date", secid, f"{secid}_volume"]]


def _future_price_scale(spec: ContractSpec | None) -> float:
    if spec is None:
        return 1.0
    scale = float(spec.lot_size) * float(spec.multiplier)
    return scale if scale > 0 else 1.0


def _min_depth(bid_depth: float | None, ask_depth: float | None) -> float | None:
    if bid_depth is None or ask_depth is None:
        return None
    if bid_depth <= 0 or ask_depth <= 0:
        return None
    return min(float(bid_depth), float(ask_depth))


def _depth_imbalance_ratio(bid_depth: float | None, ask_depth: float | None) -> float | None:
    depth_min = _min_depth(bid_depth, ask_depth)
    if depth_min is None:
        return None
    depth_max = max(float(bid_depth), float(ask_depth))
    return depth_max / depth_min if depth_min > 0 else None


def _evaluate_orderbook_gate(
    alpha_cfg: object,
    *,
    use_intraday: bool,
    spot_bid: float | None,
    spot_ask: float | None,
    fut_bid: float | None,
    fut_ask: float | None,
    stock_bid_depth: float | None,
    stock_ask_depth: float | None,
    fut_bid_depth: float | None,
    fut_ask_depth: float | None,
    stock_quote_age_sec: float | None,
    fut_quote_age_sec: float | None,
) -> tuple[bool, list[str], dict[str, float | bool | None]]:
    reasons: list[str] = []
    stock_imbalance = _depth_imbalance_ratio(stock_bid_depth, stock_ask_depth)
    fut_imbalance = _depth_imbalance_ratio(fut_bid_depth, fut_ask_depth)
    stock_min_depth = _min_depth(stock_bid_depth, stock_ask_depth)
    fut_min_depth = _min_depth(fut_bid_depth, fut_ask_depth)

    if bool(getattr(alpha_cfg, "require_live_orderbook_for_entry", False)):
        if not use_intraday:
            reasons.append("orderbook_intraday_disabled")
        if spot_bid is None or spot_ask is None:
            reasons.append("orderbook_stock_missing")
        if fut_bid is None or fut_ask is None:
            reasons.append("orderbook_fut_missing")

    min_stock_depth_cfg = getattr(alpha_cfg, "min_orderbook_depth_stock", None)
    if min_stock_depth_cfg is not None:
        if stock_min_depth is None or stock_min_depth < float(min_stock_depth_cfg):
            reasons.append("orderbook_stock_depth")

    min_fut_depth_cfg = getattr(alpha_cfg, "min_orderbook_depth_fut", None)
    if min_fut_depth_cfg is not None:
        if fut_min_depth is None or fut_min_depth < float(min_fut_depth_cfg):
            reasons.append("orderbook_fut_depth")

    stock_age_cfg = getattr(alpha_cfg, "max_orderbook_age_sec_stock", None)
    if stock_age_cfg is not None:
        if stock_quote_age_sec is None or stock_quote_age_sec > float(stock_age_cfg):
            reasons.append("orderbook_stock_stale")

    fut_age_cfg = getattr(alpha_cfg, "max_orderbook_age_sec_fut", None)
    if fut_age_cfg is not None:
        if fut_quote_age_sec is None or fut_quote_age_sec > float(fut_age_cfg):
            reasons.append("orderbook_fut_stale")

    stock_imbalance_cfg = getattr(alpha_cfg, "max_orderbook_imbalance_ratio_stock", None)
    if stock_imbalance_cfg is not None:
        if stock_imbalance is None or stock_imbalance > float(stock_imbalance_cfg):
            reasons.append("orderbook_stock_imbalance")

    fut_imbalance_cfg = getattr(alpha_cfg, "max_orderbook_imbalance_ratio_fut", None)
    if fut_imbalance_cfg is not None:
        if fut_imbalance is None or fut_imbalance > float(fut_imbalance_cfg):
            reasons.append("orderbook_fut_imbalance")

    metrics: dict[str, float | bool | None] = {
        "orderbook_pass": len(reasons) == 0,
        "orderbook_stock_min_depth": stock_min_depth,
        "orderbook_fut_min_depth": fut_min_depth,
        "orderbook_stock_imbalance": stock_imbalance,
        "orderbook_fut_imbalance": fut_imbalance,
        "orderbook_stock_quote_age_sec": stock_quote_age_sec,
        "orderbook_fut_quote_age_sec": fut_quote_age_sec,
    }
    return len(reasons) == 0, reasons, metrics


DEFAULT_ENTRY_PRICE_TOLERANCE_PCT = 0.0015


def _resolve_entry_tolerance(alpha_cfg: object) -> float:
    raw_value = getattr(
        alpha_cfg,
        "entry_price_tolerance_pct",
        DEFAULT_ENTRY_PRICE_TOLERANCE_PCT,
    )
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        value = DEFAULT_ENTRY_PRICE_TOLERANCE_PCT
    return min(max(value, 0.0001), 0.05)


def _build_signal_trade_plan(
    *,
    direction: str,
    as_of_snapshot: date,
    spot_mid: float,
    future_mid: float,
    pv_div: float,
    spread_mid_value: float,
    spread_pct_value: float,
    tp_net: float,
    sl_net: float,
    alpha_stats: object,
    alpha_cfg: object,
) -> dict[str, object]:
    entry_tolerance = _resolve_entry_tolerance(alpha_cfg)
    stock_target = float(spot_mid)
    future_target = float(future_mid)
    spread_target = float(spread_mid_value)
    direction_norm = "reverse" if str(direction).lower() == "reverse" else "cash_and_carry"

    spread_band = stock_target * entry_tolerance if stock_target > 0 else abs(spread_target) * entry_tolerance
    spread_pct_band = spread_band / stock_target if stock_target > 0 else entry_tolerance

    entry_stock_min = stock_target * (1.0 - entry_tolerance)
    entry_stock_max = stock_target * (1.0 + entry_tolerance)
    entry_future_min = future_target * (1.0 - entry_tolerance)
    entry_future_max = future_target * (1.0 + entry_tolerance)

    direction_sign = -1.0 if direction_norm == "reverse" else 1.0
    tp_spread_pct_level = spread_pct_value + direction_sign * float(tp_net)
    sl_spread_pct_level = spread_pct_value - direction_sign * float(sl_net)
    tp_spread_level = tp_spread_pct_level * stock_target
    sl_spread_level = sl_spread_pct_level * stock_target

    tp_stock_level = tp_spread_level + float(pv_div) + future_target
    sl_stock_level = sl_spread_level + float(pv_div) + future_target
    tp_future_level = stock_target - float(pv_div) - tp_spread_level
    sl_future_level = stock_target - float(pv_div) - sl_spread_level

    horizon_days = max(int(getattr(alpha_cfg, "H_max_days", 1) or 1), 1)
    half_life_raw = getattr(alpha_stats, "half_life", 0.0)
    try:
        half_life = float(half_life_raw)
    except (TypeError, ValueError):
        half_life = 0.0
    if half_life > 0:
        forecast_exit_days = int(round(min(float(horizon_days), max(1.0, half_life))))
        forecast_model = "half_life_capped"
    else:
        forecast_exit_days = horizon_days
        forecast_model = "h_max_days"
    forecast_exit_date = (as_of_snapshot + timedelta(days=forecast_exit_days)).isoformat()

    return {
        "entry_price_tolerance_pct": entry_tolerance,
        "entry_stock_min": entry_stock_min,
        "entry_stock_max": entry_stock_max,
        "entry_future_min_per_share": entry_future_min,
        "entry_future_max_per_share": entry_future_max,
        "entry_spread_min": spread_target - spread_band,
        "entry_spread_max": spread_target + spread_band,
        "entry_spread_pct_min": spread_pct_value - spread_pct_band,
        "entry_spread_pct_max": spread_pct_value + spread_pct_band,
        "tp_spread_pct_level": tp_spread_pct_level,
        "sl_spread_pct_level": sl_spread_pct_level,
        "tp_spread_level": tp_spread_level,
        "sl_spread_level": sl_spread_level,
        "tp_stock_level_if_fut_const": tp_stock_level,
        "sl_stock_level_if_fut_const": sl_stock_level,
        "tp_future_level_if_stock_const": tp_future_level,
        "sl_future_level_if_stock_const": sl_future_level,
        "forecast_tp_probability": float(getattr(alpha_stats, "p_hit_tp", 0.0) or 0.0),
        "forecast_sl_probability": float(getattr(alpha_stats, "p_hit_sl", 0.0) or 0.0),
        "forecast_exit_days": forecast_exit_days,
        "forecast_exit_date": forecast_exit_date,
        "forecast_model": forecast_model,
    }


def compute_spread_series(
    prices: pd.DataFrame,
    expiry: date,
    dividends: list[DividendEvent],
    key_rates: list[KeyRate],
    r_disc_annual: float | None = None,
    day_count: str = "ACT/365",
) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    series_rows = []
    for _, row in prices.iterrows():
        row_date = pd.to_datetime(row["date"]).date()
        spot_mid = float(row["spot"])
        future_mid = float(row["future_price"])
        key_rate_row = latest_rate(key_rates, row_date)
        key_rate_value = key_rate_row.rate if key_rate_row else 0.0
        r_disc = r_disc_annual if r_disc_annual is not None else key_rate_value
        pv_div = pv_dividends_exp(dividends, row_date, expiry, r_disc, day_count=day_count)
        div_sum_value = div_sum(dividends, row_date, expiry)
        spread_mid_value = spread_mid(spot_mid, pv_div, future_mid)
        spread_pct_value = spread_pct(spread_mid_value, spot_mid)
        series_rows.append(
            {
                "date": row_date,
                "spot_mid": spot_mid,
                "future_mid": future_mid,
                "pv_div": pv_div,
                "div_sum": div_sum_value,
                "spread_mid": spread_mid_value,
                "spread_pct": spread_pct_value,
            }
        )
    return pd.DataFrame(series_rows)


RECENT_TRADES_WINDOW = 5


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
    if merged is not None and {"spot_volume", "future_volume"}.issubset(merged.columns):
        series_df = series_df.merge(
            merged[["date", "spot_volume", "future_volume"]],
            on="date",
            how="left",
        )

    spreads_pct = series_df["spread_pct"].tolist()
    signal_actions: list[str] = []
    signal_directions: list[str | None] = []
    entry_flags: list[bool] = []
    exit_flags: list[bool] = []
    entry_spread_pcts: list[float | None] = []
    exit_spread_pcts: list[float | None] = []
    trade_cycles: list[int | None] = []
    trade_returns: list[float | None] = []
    trade_pnls: list[float | None] = []
    trade_return_pct_net: list[float | None] = []
    trade_return_annual: list[float | None] = []
    trade_hold_days: list[int | None] = []
    rtc_pcts: list[float] = []
    tp_nets: list[float] = []
    sl_nets: list[float] = []
    floor_rates: list[float] = []
    floor_passes: list[bool] = []
    liquidity_passes: list[bool] = []
    zscores: list[float] = []
    state = SpreadCarryState()
    current_entry_spread_pct: float | None = None
    current_entry_spot_exec: float | None = None
    current_entry_fut_exec: float | None = None
    current_entry_date: date | None = None
    current_entry_stock_fee: float | None = None
    current_entry_fut_fee: float | None = None
    current_cycle = 0

    for idx, row in series_df.iterrows():
        row_date = row["date"]
        spot_mid = float(row["spot_mid"])
        future_mid = float(row["future_mid"])
        key_rate_row = latest_rate(key_rates, row_date)
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
            div_sum=float(row.get("div_sum", 0.0)),
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

        spot_volume = row.get("spot_volume")
        fut_volume = row.get("future_volume")
        dollar_vol_stock = dollar_volume(spot_mid, spot_volume)
        dollar_vol_fut = dollar_volume(future_mid, fut_volume, future_spec.multiplier)
        avg_dollar = None
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
            exec_prices.stock_buy, float(row.get("pv_div", 0.0)), exec_prices.fut_sell
        )
        spread_exit_exec_value = spread_exit_exec(
            exec_prices.stock_sell, float(row.get("pv_div", 0.0)), exec_prices.fut_buy
        )
        spread_pct_entry_exec = spread_pct(spread_entry_exec_value, spot_mid)
        spread_pct_exit_exec = spread_pct(spread_exit_exec_value, spot_mid)

        decision = step_spread_carry_alpha(
            state,
            as_of=row_date,
            floor_pass=floor_metrics.floor_pass,
            liquidity_pass=liquidity_pass,
            spread_pct_entry_exec=spread_pct_entry_exec,
            spread_pct_exit_exec=spread_pct_exit_exec,
            tp_net=tp_net,
            sl_net=sl_net,
            dte=dte,
            min_dte_entry=alpha_cfg.min_DTE_entry,
            close_buffer_days=alpha_cfg.close_buffer_days,
            h_max_days=alpha_cfg.H_max_days,
            entry_filter_ok=entry_filter_ok,
        )

        signal_actions.append(decision.action)
        signal_directions.append(decision.direction)
        is_entry = decision.action == "enter"
        is_exit = decision.action == "exit"
        entry_flags.append(is_entry)
        exit_flags.append(is_exit)
        if is_entry:
            current_cycle += 1
            current_entry_spread_pct = spread_pct_entry_exec
            current_entry_spot_exec = exec_prices.stock_buy
            current_entry_fut_exec = exec_prices.fut_sell
            current_entry_date = row_date
            current_entry_stock_fee = stock_fee
            current_entry_fut_fee = fut_fee
            entry_spread_pcts.append(spread_pct_entry_exec)
            exit_spread_pcts.append(None)
            trade_cycles.append(current_cycle)
            trade_returns.append(None)
            trade_pnls.append(None)
            trade_return_pct_net.append(None)
            trade_return_annual.append(None)
            trade_hold_days.append(None)
        elif is_exit:
            entry_spread_pcts.append(None)
            exit_spread_pcts.append(spread_pct_exit_exec)
            trade_cycles.append(current_cycle if current_cycle > 0 else None)
            trade_returns.append(
                (spread_pct_exit_exec - current_entry_spread_pct)
                if current_entry_spread_pct is not None
                else None
            )
            trade_pnl = None
            trade_return_net = None
            trade_return_ann = None
            hold_days_value = None
            if (
                current_entry_spot_exec is not None
                and current_entry_fut_exec is not None
                and current_entry_date is not None
            ):
                dividend_cash = sum(
                    event.amount
                    for event in dividends
                    if current_entry_date < event.ex_date <= row_date
                )
                hold_tau = year_fraction(current_entry_date, row_date, alpha_cfg.day_count)
                funding_cost = current_entry_spot_exec * r_fund * hold_tau
                exit_stock_fee = stock_fee
                exit_fut_fee = fut_fee
                entry_stock_fee = current_entry_stock_fee or 0.0
                entry_fut_fee = current_entry_fut_fee or 0.0
                fees_total = entry_stock_fee + entry_fut_fee + exit_stock_fee + exit_fut_fee
                trade_pnl = (
                    (exec_prices.stock_sell - current_entry_spot_exec)
                    - (exec_prices.fut_buy - current_entry_fut_exec)
                    + dividend_cash
                    - funding_cost
                    - fees_total
                )
                trade_return_net = trade_pnl / current_entry_spot_exec if current_entry_spot_exec else None
                trade_return_ann = (
                    trade_return_net / hold_tau if hold_tau > 0 and trade_return_net is not None else None
                )
                hold_days_value = (row_date - current_entry_date).days
            trade_pnls.append(trade_pnl)
            trade_return_pct_net.append(trade_return_net)
            trade_return_annual.append(trade_return_ann)
            trade_hold_days.append(hold_days_value)
            current_entry_spread_pct = None
            current_entry_spot_exec = None
            current_entry_fut_exec = None
            current_entry_date = None
            current_entry_stock_fee = None
            current_entry_fut_fee = None
        else:
            entry_spread_pcts.append(None)
            exit_spread_pcts.append(None)
            trade_cycles.append(None)
            trade_returns.append(None)
            trade_pnls.append(None)
            trade_return_pct_net.append(None)
            trade_return_annual.append(None)
            trade_hold_days.append(None)
        rtc_pcts.append(rtc_pct)
        tp_nets.append(tp_net)
        sl_nets.append(sl_net)
        floor_rates.append(floor_metrics.floor_rate_annual)
        floor_passes.append(floor_metrics.floor_pass)
        liquidity_passes.append(liquidity_pass)
        zscores.append(z)

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
    series_df["trade_hold_days"] = trade_hold_days
    series_df["rtc_pct"] = rtc_pcts
    series_df["tp_net"] = tp_nets
    series_df["sl_net"] = sl_nets
    series_df["floor_rate_annual"] = floor_rates
    series_df["floor_pass"] = floor_passes
    series_df["liquidity_pass"] = liquidity_passes
    series_df["zscore"] = zscores
    return series_df


def _avg_recent_trade_return_annual(series_df: pd.DataFrame) -> float | None:
    if series_df.empty or "trade_return_annual" not in series_df.columns:
        return None
    exits = series_df.loc[
        series_df.get("exit_flag", False) & series_df["trade_return_annual"].notna(),
        "trade_return_annual",
    ]
    if exits.empty:
        return None
    return float(exits.tail(RECENT_TRADES_WINDOW).mean())


def build_spread_series(
    settings: AppSettings,
    stock_secid: str,
    future_secid: str,
    window_days: int = 60,
    full_life: bool = False,
) -> pd.DataFrame:
    paths = resolve_paths(settings)
    dirs = _data_paths(paths.data_dir)
    futures_path = dirs["raw"] / "futures.csv"
    if not futures_path.exists():
        return pd.DataFrame()
    futures_df = pd.read_csv(futures_path)
    future_spec_map = {spec.secid: spec for spec in _parse_contract_specs(futures_df)}
    future_spec = future_spec_map.get(future_secid)
    if future_spec is None or not future_spec.expiry:
        return pd.DataFrame()
    future_scale = _future_price_scale(future_spec)

    today = date.today()
    if full_life:
        lookback = future_spec.expiry - timedelta(days=365)
    else:
        lookback_days = max(int(window_days), 1)
        lookback = today - timedelta(days=lookback_days)
    client = MoexIssClient(settings.moex.base_url, settings.moex.request_timeout_sec)

    stock_candles = _fetch_candles(
        client,
        settings.moex.engine_shares,
        settings.moex.market_shares,
        settings.moex.shares_board,
        stock_secid,
        lookback,
        today,
    )
    future_candles = _fetch_candles(
        client,
        settings.moex.engine_futures,
        settings.moex.market_futures,
        settings.moex.futures_board,
        future_secid,
        lookback,
        today,
        price_scale=future_scale,
    )
    if stock_candles.empty or future_candles.empty:
        return pd.DataFrame()
    merged = pd.merge(stock_candles, future_candles, on="date", how="inner")
    if merged.empty:
        return pd.DataFrame()
    merged.rename(
        columns={
            stock_secid: "spot",
            future_secid: "future_price",
            f"{stock_secid}_volume": "spot_volume",
            f"{future_secid}_volume": "future_volume",
        },
        inplace=True,
    )

    dividends = _load_dividends(client, stock_secid, paths.data_dir)
    key_rates = _load_key_rates(dirs["raw"] / "key_rates.csv")
    alpha_cfg = settings.spread_carry_alpha
    series_df = compute_spread_series(
        merged[["date", "spot", "future_price"]],
        future_spec.expiry,
        dividends,
        key_rates,
        r_disc_annual=alpha_cfg.r_disc_annual,
        day_count=alpha_cfg.day_count,
    )
    if series_df.empty:
        return series_df

    return _apply_spread_carry_signals(
        series_df,
        merged=merged,
        dividends=dividends,
        key_rates=key_rates,
        settings=settings,
        future_spec=future_spec,
        alpha_cfg=alpha_cfg,
    )


def compute_pairs(
    settings: AppSettings,
    return_df: bool = False,
    max_pairs: int | None = None,
    save_csv: bool = True,
    as_of: date | None = None,
) -> pd.DataFrame | None:
    paths = resolve_paths(settings)
    dirs = _data_paths(paths.data_dir)

    shares_df = pd.read_csv(dirs["raw"] / "shares.csv")
    futures_df = pd.read_csv(dirs["raw"] / "futures.csv")
    instruments = _parse_instruments(shares_df)
    futures_specs = _parse_contract_specs(futures_df)
    mappings = build_pair_mappings(instruments, futures_specs)
    instrument_map = {instrument.secid: instrument for instrument in instruments}
    future_spec_map = {spec.secid: spec for spec in futures_specs}

    key_rates = _load_key_rates(dirs["raw"] / "key_rates.csv")
    client = MoexIssClient(settings.moex.base_url, settings.moex.request_timeout_sec)

    requested_as_of = as_of
    as_of_date = requested_as_of or date.today()
    lookback_days = max(settings.data.compute_lookback_days, 1)
    lookback = as_of_date - timedelta(days=lookback_days)
    results = []

    limit = max_pairs if max_pairs is not None else settings.strategy.max_pairs
    selected = mappings if limit == 0 else mappings[: max(limit, 1)]
    for mapping in selected:
        expiry = mapping.expiry
        if expiry <= as_of_date:
            continue
        alpha_cfg = settings.spread_carry_alpha
        allowed_months = alpha_cfg.allowed_expiry_months or []
        allowed_years = alpha_cfg.allowed_expiry_years or []
        if allowed_months and expiry.month not in allowed_months:
            continue
        if allowed_years and expiry.year not in allowed_years:
            continue
        stock_candles = _fetch_candles(
            client,
            settings.moex.engine_shares,
            settings.moex.market_shares,
            settings.moex.shares_board,
            mapping.stock_secid,
            lookback,
            as_of_date,
        )
        future_spec = future_spec_map.get(mapping.future_secid)
        if future_spec is None:
            continue
        future_scale = _future_price_scale(future_spec)
        future_candles = _fetch_candles(
            client,
            settings.moex.engine_futures,
            settings.moex.market_futures,
            settings.moex.futures_board,
            mapping.future_secid,
            lookback,
            as_of_date,
            price_scale=future_scale,
        )
        if stock_candles.empty or future_candles.empty:
            continue
        merged = pd.merge(stock_candles, future_candles, on="date", how="inner")
        if merged.empty:
            continue
        merged.rename(
            columns={
                mapping.stock_secid: "spot",
                mapping.future_secid: "future",
                f"{mapping.stock_secid}_volume": "spot_volume",
                f"{mapping.future_secid}_volume": "future_volume",
            },
            inplace=True,
        )
        latest = merged.iloc[-1]
        if requested_as_of is not None and latest["date"] != as_of_date:
            continue
        as_of_snapshot = latest["date"]
        snapshot_payload = merged.to_csv(index=False).encode("utf-8")
        snapshot = build_snapshot(
            source="MOEX_ISS",
            instrument=f"{mapping.stock_secid}-{mapping.future_secid}",
            as_of=as_of_snapshot,
            payload=snapshot_payload,
            is_cached=False,
        )

        dividends = _load_dividends(client, mapping.stock_secid, paths.data_dir)
        series_df = compute_spread_series(
            merged[["date", "spot", "future"]].rename(columns={"future": "future_price"}),
            expiry,
            dividends,
            key_rates,
            r_disc_annual=alpha_cfg.r_disc_annual,
            day_count=alpha_cfg.day_count,
        )
        if series_df.empty:
            continue

        spot_mid = float(latest["spot"])
        future_mid = float(latest["future"])
        spot_bid = None
        spot_ask = None
        fut_bid = None
        fut_ask = None
        stock_bid_depth = None
        stock_ask_depth = None
        fut_bid_depth = None
        fut_ask_depth = None
        stock_quote_age_sec = None
        fut_quote_age_sec = None
        open_interest = None
        use_intraday = settings.strategy.intraday_marketdata and (
            requested_as_of is None or as_of_date == date.today()
        )
        if use_intraday:
            stock_quotes = client.get_marketdata(
                settings.moex.engine_shares,
                settings.moex.market_shares,
                settings.moex.shares_board,
                mapping.stock_secid,
            )
            if stock_quotes:
                stock_point = build_stock_point(stock_quotes[0])
                spot_mid = stock_point.mid or spot_mid
                spot_bid = stock_point.bid
                spot_ask = stock_point.ask
                stock_bid_depth = stock_point.bid_depth
                stock_ask_depth = stock_point.ask_depth
                stock_quote_age_sec = stock_point.quote_age_sec
            future_quotes = client.get_marketdata(
                settings.moex.engine_futures,
                settings.moex.market_futures,
                settings.moex.futures_board,
                mapping.future_secid,
            )
            if future_quotes:
                fut_point = build_fut_point(future_quotes[0])
                scale = future_scale if future_scale and future_scale > 0 else 1.0
                fut_bid = fut_point.bid / scale if fut_point.bid is not None else None
                fut_ask = fut_point.ask / scale if fut_point.ask is not None else None
                fut_mid = fut_point.mid / scale if fut_point.mid is not None else None
                fut_last = fut_point.last / scale if fut_point.last is not None else None
                future_mid = fut_mid or fut_last or future_mid
                open_interest = fut_point.open_interest
                fut_bid_depth = fut_point.bid_depth
                fut_ask_depth = fut_point.ask_depth
                fut_quote_age_sec = fut_point.quote_age_sec

        key_rate = latest_rate(key_rates, as_of_snapshot)
        key_rate_value = key_rate.rate if key_rate else 0.0
        r_cb = alpha_cfg.r_cb_annual if alpha_cfg.r_cb_annual is not None else key_rate_value
        r_fund = alpha_cfg.r_fund_annual if alpha_cfg.r_fund_annual is not None else r_cb
        r_disc = alpha_cfg.r_disc_annual if alpha_cfg.r_disc_annual is not None else r_cb
        pv_div = pv_dividends_exp(
            dividends, as_of_snapshot, expiry, r_disc, day_count=alpha_cfg.day_count
        )
        div_sum_value = div_sum(dividends, as_of_snapshot, expiry)
        spread_mid_value = spread_mid(spot_mid, pv_div, future_mid)
        spread_pct_value = spread_pct(spread_mid_value, spot_mid)
        if not series_df.empty:
            last_idx = series_df.index[-1]
            series_df.at[last_idx, "spot_mid"] = spot_mid
            series_df.at[last_idx, "future_mid"] = future_mid
            series_df.at[last_idx, "pv_div"] = pv_div
            series_df.at[last_idx, "div_sum"] = div_sum_value
            series_df.at[last_idx, "spread_mid"] = spread_mid_value
            series_df.at[last_idx, "spread_pct"] = spread_pct_value

        series_with_signals = _apply_spread_carry_signals(
            series_df,
            merged=merged,
            dividends=dividends,
            key_rates=key_rates,
            settings=settings,
            future_spec=future_spec,
            alpha_cfg=alpha_cfg,
        )
        avg_trade_return_annual = _avg_recent_trade_return_annual(series_with_signals)

        dte = days_to_expiry(as_of_snapshot, expiry, alpha_cfg.use_trading_days)
        tau = year_fraction(as_of_snapshot, expiry, alpha_cfg.day_count)

        exec_prices = build_execution_prices(
            stock_bid=spot_bid,
            stock_ask=spot_ask,
            fut_bid=fut_bid,
            fut_ask=fut_ask,
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

        spread_bps_stock_value = spread_bps(spot_bid, spot_ask, spot_mid)
        spread_bps_fut_value = spread_bps(fut_bid, fut_ask, future_mid)
        dollar_vol_stock = dollar_volume(spot_mid, latest.get("spot_volume"))
        dollar_vol_fut = dollar_volume(future_mid, latest.get("future_volume"), future_spec.multiplier)
        avg_dollar = None
        if dollar_vol_stock is not None and dollar_vol_fut is not None:
            avg_dollar = min(dollar_vol_stock, dollar_vol_fut)
        else:
            avg_dollar = dollar_vol_stock or dollar_vol_fut
        position_notional = alpha_cfg.capital_allocated_per_trade
        if position_notional is None and alpha_cfg.max_contracts_per_pair > 0:
            position_notional = spot_mid * future_spec.multiplier * alpha_cfg.max_contracts_per_pair
        days_exit = days_to_exit(position_notional, avg_dollar, alpha_cfg.participation_rate)
        liquidity_pass = evaluate_liquidity(
            spread_bps_stock_value=spread_bps_stock_value,
            spread_bps_fut_value=spread_bps_fut_value,
            dollar_vol_stock_value=dollar_vol_stock,
            dollar_vol_fut_value=dollar_vol_fut,
            open_interest=open_interest,
            days_to_exit_value=days_exit,
            max_spread_bps_stock=alpha_cfg.max_spread_bps_stock,
            max_spread_bps_fut=alpha_cfg.max_spread_bps_fut,
            min_dollar_vol_stock=alpha_cfg.min_avg_dollarvol_stock,
            min_dollar_vol_fut=alpha_cfg.min_avg_dollarvol_fut,
            min_open_interest=alpha_cfg.min_open_interest,
            max_days_to_exit=alpha_cfg.max_days_to_exit,
        )
        orderbook_pass, orderbook_reasons, orderbook_metrics = _evaluate_orderbook_gate(
            alpha_cfg,
            use_intraday=use_intraday,
            spot_bid=spot_bid,
            spot_ask=spot_ask,
            fut_bid=fut_bid,
            fut_ask=fut_ask,
            stock_bid_depth=stock_bid_depth,
            stock_ask_depth=stock_ask_depth,
            fut_bid_depth=fut_bid_depth,
            fut_ask_depth=fut_ask_depth,
            stock_quote_age_sec=stock_quote_age_sec,
            fut_quote_age_sec=fut_quote_age_sec,
        )

        spread_pct_series = series_df["spread_pct"].tolist()
        alpha_stats = alpha_metrics(spread_pct_series, horizon=alpha_cfg.H_max_days, tp=tp_net, sl=alpha_cfg.SL_pct)
        trade_plan_metrics = _build_signal_trade_plan(
            direction="cash_and_carry",
            as_of_snapshot=as_of_snapshot,
            spot_mid=spot_mid,
            future_mid=future_mid,
            pv_div=pv_div,
            spread_mid_value=spread_mid_value,
            spread_pct_value=spread_pct_value,
            tp_net=tp_net,
            sl_net=sl_net,
            alpha_stats=alpha_stats,
            alpha_cfg=alpha_cfg,
        )
        score_floor = floor_metrics.floor_rate_annual - r_cb
        score_alpha = alpha_stats.p_hit_tp * tp_net - alpha_stats.p_hit_sl * alpha_cfg.SL_pct - rtc_pct
        penalty_liq = 0.0
        if alpha_cfg.max_spread_bps_stock is not None and spread_bps_stock_value is not None:
            penalty_liq += alpha_cfg.c1 * max(0.0, spread_bps_stock_value - alpha_cfg.max_spread_bps_stock)
        if alpha_cfg.max_spread_bps_fut is not None and spread_bps_fut_value is not None:
            penalty_liq += alpha_cfg.c2 * max(0.0, spread_bps_fut_value - alpha_cfg.max_spread_bps_fut)
        penalty_event = 0.0
        total_score = (
            alpha_cfg.w1 * score_floor
            + alpha_cfg.w2 * score_alpha
            - alpha_cfg.w3 * penalty_liq
            - alpha_cfg.w4 * penalty_event
        )

        decision = "ENTER_OK"
        if not floor_metrics.floor_pass:
            decision = "SKIP_FLOOR"
        elif not liquidity_pass:
            decision = "SKIP_LIQUIDITY"
        elif not orderbook_pass:
            decision = "SKIP_ORDERBOOK"
        elif alpha_cfg.min_floor_score is not None and score_floor < alpha_cfg.min_floor_score:
            decision = "SKIP_SCORE"
        elif alpha_cfg.min_alpha_score is not None and score_alpha < alpha_cfg.min_alpha_score:
            decision = "SKIP_SCORE"
        elif alpha_cfg.min_total_score is not None and total_score < alpha_cfg.min_total_score:
            decision = "SKIP_SCORE"

        signal_action = "enter" if decision == "ENTER_OK" else "hold"
        signal_direction = "cash_and_carry" if decision == "ENTER_OK" else None
        signal_reasons = [decision.lower()]
        if decision == "SKIP_ORDERBOOK":
            signal_reasons.extend(orderbook_reasons)
        signal_metrics = {
            "spread_pct": spread_pct_value,
            "rtc_pct": rtc_pct,
            "floor_rate_annual": floor_metrics.floor_rate_annual,
            "tp_net": tp_net,
            "sl_net": sl_net,
            "p_hit_tp": alpha_stats.p_hit_tp,
            "p_hit_sl": alpha_stats.p_hit_sl,
            "score_floor": score_floor,
            "score_alpha": score_alpha,
            "total_score": total_score,
            "orderbook_pass": orderbook_pass,
            "orderbook_reasons": orderbook_reasons,
            "orderbook_stock_quote_age_sec": orderbook_metrics["orderbook_stock_quote_age_sec"],
            "orderbook_fut_quote_age_sec": orderbook_metrics["orderbook_fut_quote_age_sec"],
            "orderbook_stock_min_depth": orderbook_metrics["orderbook_stock_min_depth"],
            "orderbook_fut_min_depth": orderbook_metrics["orderbook_fut_min_depth"],
            "orderbook_stock_imbalance": orderbook_metrics["orderbook_stock_imbalance"],
            "orderbook_fut_imbalance": orderbook_metrics["orderbook_fut_imbalance"],
            **trade_plan_metrics,
        }
        stock_name = (
            instrument_map.get(mapping.stock_secid).name
            if mapping.stock_secid in instrument_map
            else mapping.stock_secid
        )
        results.append(
            {
                "stock": mapping.stock_secid,
                "stock_name": stock_name,
                "future": mapping.future_secid,
                "expiry": expiry,
                "spot": spot_mid,
                "future_price": future_mid,
                "spread_mid": spread_mid_value,
                "spread_pct": spread_pct_value,
                "rtc_pct": rtc_pct,
                "floor_rate_annual": floor_metrics.floor_rate_annual,
                "score_floor": score_floor,
                "score_alpha": score_alpha,
                "total_score": total_score,
                "decision": decision,
                "floor_pass": floor_metrics.floor_pass,
                "liquidity_pass": liquidity_pass,
                "orderbook_pass": orderbook_pass,
                "dte": dte,
                "p_hit_tp": alpha_stats.p_hit_tp,
                "p_hit_sl": alpha_stats.p_hit_sl,
                "tp_net": tp_net,
                "sl_net": sl_net,
                "sigma_h": alpha_stats.sigma_h,
                "half_life": alpha_stats.half_life,
                "spread_bps_stock": spread_bps_stock_value,
                "spread_bps_fut": spread_bps_fut_value,
                "stock_bid_depth": stock_bid_depth,
                "stock_ask_depth": stock_ask_depth,
                "fut_bid_depth": fut_bid_depth,
                "fut_ask_depth": fut_ask_depth,
                "stock_quote_age_sec": stock_quote_age_sec,
                "fut_quote_age_sec": fut_quote_age_sec,
                "stock_depth_imbalance": orderbook_metrics["orderbook_stock_imbalance"],
                "fut_depth_imbalance": orderbook_metrics["orderbook_fut_imbalance"],
                "dollar_vol_stock": dollar_vol_stock,
                "dollar_vol_fut": dollar_vol_fut,
                "days_to_exit": days_exit,
                "open_interest": open_interest,
                "r_cb_annual": r_cb,
                "r_fund_annual": r_fund,
                "r_disc_annual": r_disc,
                "avg_trade_return_annual_recent": avg_trade_return_annual,
                "signal_action": signal_action,
                "signal_direction": signal_direction,
                "signal_score": total_score,
                "signal_reasons": signal_reasons,
                "signal_metrics": signal_metrics,
                "orderbook_reasons": orderbook_reasons,
                "snapshot_id": snapshot["snapshot_id"],
                "snapshot_hash": snapshot["hash"],
                "snapshot_as_of": snapshot["as_of"],
                **trade_plan_metrics,
            }
        )

    if not results:
        return pd.DataFrame() if return_df else None
    metrics_df = pd.DataFrame(results)
    ranked = score_pairs_alpha(metrics_df)
    if save_csv:
        top_pairs = ranked.drop(columns=["signal_reasons", "signal_metrics"], errors="ignore")
        top_pairs.to_csv(dirs["output"] / "top_pairs.csv", index=False)
        ranked[
            [
                "stock",
                "stock_name",
                "future",
                "signal_action",
                "signal_direction",
                "signal_score",
                "spread_pct",
                "floor_rate_annual",
                "entry_spread_pct_min",
                "entry_spread_pct_max",
                "tp_spread_pct_level",
                "sl_spread_pct_level",
                "forecast_exit_days",
                "forecast_exit_date",
                "tp_net",
                "sl_net",
                "signal_reasons",
                "signal_metrics",
            ]
        ].to_csv(dirs["output"] / "signals.csv", index=False)
    if return_df:
        return ranked
    return None


def run_backtest(settings: AppSettings) -> BacktestResult | None:
    paths = resolve_paths(settings)
    dirs = _data_paths(paths.data_dir)
    top_pairs_path = dirs["output"] / "top_pairs.csv"
    if not top_pairs_path.exists():
        return None
    top_pairs = pd.read_csv(top_pairs_path)
    if top_pairs.empty:
        return None
    row = top_pairs.iloc[0]
    stock_secid = row["stock"]
    future_secid = row["future"]
    expiry = pd.to_datetime(row["expiry"]).date()

    futures_df = pd.read_csv(dirs["raw"] / "futures.csv")
    future_spec_map = {spec.secid: spec for spec in _parse_contract_specs(futures_df)}
    future_spec = future_spec_map.get(future_secid)
    future_scale = _future_price_scale(future_spec)
    client = MoexIssClient(settings.moex.base_url, settings.moex.request_timeout_sec)
    today = date.today()
    lookback_days = max(settings.data.backtest_lookback_days, 1)
    lookback = today - timedelta(days=lookback_days)
    stock_candles = _fetch_candles(
        client,
        settings.moex.engine_shares,
        settings.moex.market_shares,
        settings.moex.shares_board,
        stock_secid,
        lookback,
        today,
    )
    future_candles = _fetch_candles(
        client,
        settings.moex.engine_futures,
        settings.moex.market_futures,
        settings.moex.futures_board,
        future_secid,
        lookback,
        today,
        price_scale=future_scale,
    )
    if stock_candles.empty or future_candles.empty:
        return None
    merged = pd.merge(stock_candles, future_candles, on="date", how="inner")
    merged.rename(columns={stock_secid: "spot", future_secid: "future"}, inplace=True)

    dividends = _load_dividends(client, stock_secid, paths.data_dir)
    key_rates = _load_key_rates(dirs["raw"] / "key_rates.csv")
    cost_profile = CostProfile(
        stock_commission_bps=settings.costs.stock_commission_bps,
        futures_commission_bps=settings.costs.futures_commission_bps,
        exchange_fee_bps=settings.costs.exchange_fee_bps,
        slippage_bps=settings.costs.slippage_bps,
    )
    tax_profile = TaxProfile(
        profit_tax_rate=settings.taxes.profit_tax_rate,
        dividend_tax_rate=settings.taxes.dividend_tax_rate,
    )
    alpha_cfg = settings.spread_carry_alpha
    multiplier = future_spec.multiplier if future_spec else 1.0
    tick_size = future_spec.price_step if future_spec else None
    result = backtest_pair(
        prices=merged[["date", "spot", "future"]],
        expiry=expiry,
        dividends=dividends,
        key_rates=key_rates,
        costs=cost_profile,
        taxes=tax_profile,
        strategy_config=alpha_cfg,
        multiplier=multiplier,
        tick_size_fut=tick_size,
    )
    summary = pd.DataFrame([result.metrics])
    summary.to_csv(dirs["output"] / "backtest_summary.csv", index=False)
    return result


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


def run_paper_trading(settings: AppSettings, use_existing: bool = True) -> None:
    paths = resolve_paths(settings)
    dirs = _data_paths(paths.data_dir)
    top_pairs_path = dirs["output"] / "top_pairs.csv"
    if use_existing and top_pairs_path.exists():
        ranked = pd.read_csv(top_pairs_path)
    else:
        ranked = compute_pairs(settings, return_df=True)
    if ranked is None or ranked.empty:
        return
    backtest_summary_path = dirs["output"] / "backtest_summary.csv"
    if use_existing and backtest_summary_path.exists():
        backtest_summary = pd.read_csv(backtest_summary_path)
        backtest_metrics = backtest_summary.iloc[0].to_dict() if not backtest_summary.empty else {}
    else:
        result = run_backtest(settings)
        backtest_metrics = result.metrics if result else {}
    top = ranked.iloc[0]
    decision_id = f"decision-{pd.Timestamp.utcnow().strftime('%Y%m%d%H%M%S')}"
    decision_view_id = f"view-{decision_id}"
    created_at = pd.Timestamp.utcnow().isoformat()
    snapshot_entry = {
        "source": "MOEX_ISS",
        "snapshot_id": top.get("snapshot_id", ""),
        "as_of": top.get("snapshot_as_of", created_at),
        "hash": top.get("snapshot_hash", ""),
        "is_cached": False,
    }
    feature_list = [
        {"name": "spread_mid", "value": float(top.get("spread_mid", 0.0)), "units": "price"},
        {"name": "spread_pct", "value": float(top.get("spread_pct", 0.0)), "units": "pct"},
        {
            "name": "floor_rate_annual",
            "value": float(top.get("floor_rate_annual", 0.0)),
            "units": "rate",
        },
        {"name": "rtc_pct", "value": float(top.get("rtc_pct", 0.0)), "units": "pct"},
        {"name": "total_score", "value": float(top.get("total_score", 0.0)), "units": "score"},
    ]
    signal_action_raw = top.get("signal_action", "hold")
    signal_action = str(signal_action_raw) if pd.notna(signal_action_raw) else "hold"
    signal_direction_raw = top.get("signal_direction", "neutral")
    signal_direction = str(signal_direction_raw) if pd.notna(signal_direction_raw) else "neutral"
    signal_score = float(top.get("signal_score", 0.0))
    signal_direction_map = {
        "cash_and_carry": "long",
        "reverse": "short",
        "neutral": "neutral",
    }
    mapped_direction = signal_direction_map.get(signal_direction, "neutral")
    signal_entry = {
        "name": "stock_futures_spread_carry_alpha",
        "value": signal_score,
        "direction": mapped_direction,
        "confidence": min(abs(signal_score), 1.0),
        "units": "score",
    }
    rules = [
        {"id": "signal_action", "result": signal_action == "enter", "severity": "info"},
        {"id": "signal_direction", "result": mapped_direction != "neutral", "severity": "info"},
    ]
    base_proposal = build_portfolio_proposal(
        signal_action=signal_action,
        signal_direction=signal_direction if signal_direction != "neutral" else None,
        stock_secid=str(top.get("stock", "")),
        future_secid=str(top.get("future", "")),
    )
    expected_return_raw = top.get("floor_rate_annual", None)
    expected_return = (
        float(expected_return_raw) if pd.notna(expected_return_raw) else None
    )
    spread_payload = {
        "strategy_id": "stock_futures_spread_carry_alpha_v1",
        "strategy_type": "arbitrage",
        "cadence": settings.aggregation.rebalance_cadence,
        "horizon": "short",
        "action": signal_action,
        "confidence": min(abs(signal_score), 1.0),
        "expected_return": expected_return,
        "risk_estimate": float(top.get("sigma_h", 0.0)) if pd.notna(top.get("sigma_h")) else None,
        "instruments": [str(top.get("stock", "")), str(top.get("future", ""))],
        "intent_allocations": base_proposal.get("allocations", []),
        "rules_evaluated": [
            {
                "rule_id": rule["id"],
                "result": rule["result"],
                "severity": rule.get("severity", "info"),
            }
            for rule in rules
        ],
        "warnings": [],
        "metadata": {
            "spread_pct": float(top.get("spread_pct", 0.0)) if pd.notna(top.get("spread_pct")) else None,
            "rtc_pct": float(top.get("rtc_pct", 0.0)) if pd.notna(top.get("rtc_pct")) else None,
            "floor_rate_annual": float(top.get("floor_rate_annual", 0.0))
            if pd.notna(top.get("floor_rate_annual"))
            else None,
            "score_floor": float(top.get("score_floor", 0.0)) if pd.notna(top.get("score_floor")) else None,
            "score_alpha": float(top.get("score_alpha", 0.0)) if pd.notna(top.get("score_alpha")) else None,
            "total_score": float(top.get("total_score", 0.0)) if pd.notna(top.get("total_score")) else None,
            "decision": str(top.get("decision", "")) if pd.notna(top.get("decision")) else None,
        },
    }
    strategy_signals = load_spread_signals([spread_payload])
    aggregation_result = aggregate_strategy_signals(
        strategy_signals,
        settings.aggregation.weights,
        settings.aggregation.min_confidence,
        settings.aggregation.max_signals,
    )
    proposal = {"allocations": aggregation_result.allocations}
    allocations = proposal["allocations"]
    risk_profile = _risk_profile_from_settings(settings)
    risk_gate = evaluate_risk_profile(risk_profile, allocations)
    news_items: list[NewsItem] = []
    news_gate = apply_news_filter(
        news_items,
        lookback_minutes=settings.news_filter.lookback_minutes,
        block_severity_threshold=settings.news_filter.block_severity_threshold,
        reduce_severity_threshold=settings.news_filter.reduce_severity_threshold,
    )
    futures_path = dirs["raw"] / "futures.csv"
    futures_df = pd.read_csv(futures_path) if futures_path.exists() else pd.DataFrame()
    future_spec_map = {spec.secid: spec for spec in _parse_contract_specs(futures_df)} if not futures_df.empty else {}
    cost_profile = CostProfile(
        stock_commission_bps=settings.costs.stock_commission_bps,
        futures_commission_bps=settings.costs.futures_commission_bps,
        exchange_fee_bps=settings.costs.exchange_fee_bps,
        slippage_bps=settings.costs.slippage_bps,
    )
    cost_model = _build_cost_model(
        cost_profile,
        float(top.get("future_price", 0.0)),
        future_spec_map.get(str(top.get("future", ""))),
    )
    action = "hold"
    if risk_gate.action == "block" or news_gate.action == "block":
        action = "reject"
    elif aggregation_result.action in {"enter", "exit"}:
        action = "approve"
    if risk_gate.action == "block" or news_gate.action == "block":
        risk_state = "red"
    elif risk_gate.action == "reduce" or news_gate.action == "reduce":
        risk_state = "yellow"
    else:
        risk_state = "green"
    decision_reasons = list(aggregation_result.reasons)
    decision_reasons.extend(
        [check.check_id for check in risk_gate.checks if not check.passed]
    )
    decision_warnings = list(aggregation_result.warnings)
    decision_warnings.extend(news_gate.errors)
    decision_reasons = list(dict.fromkeys(decision_reasons))
    decision_warnings = list(dict.fromkeys(decision_warnings))
    decision_log = {
        "schema_version": "1.0.0",
        "decision_id": decision_id,
        "created_at": created_at,
        "run_id": f"run-{decision_id}",
        "environment": {
            "mode": settings.environment.mode,
            "venue": settings.environment.venue,
            "timezone": settings.environment.timezone,
        },
        "input_snapshots": [snapshot_entry],
        "feature_set": {
            "feature_version": "v1",
            "features": feature_list,
            "snapshot_ids": [snapshot_entry.get("snapshot_id", "")],
        },
        "strategies": [
            {
                "name": "stock_futures_spread_carry_alpha",
                "type": "arbitrage",
                "enabled": True,
                "signals": [signal_entry],
                "rules_evaluated": rules,
            }
        ],
        "strategy_signals": [strategy_signal_to_dict(signal) for signal in strategy_signals],
        "aggregation": {
            "action": aggregation_result.action,
            "score": aggregation_result.score,
            "weights": aggregation_result.weights,
            "used_strategies": aggregation_result.used_strategies,
            "blocked_strategies": aggregation_result.blocked_strategies,
            "reasons": aggregation_result.reasons,
            "warnings": aggregation_result.warnings,
        },
        "news_context": {
            "severity": news_gate.highest_severity,
            "headline_count": len(news_gate.matched_items),
            "summary": news_gate.action,
        },
        "portfolio_proposal": proposal,
        "risk_checks": [
            {
                "id": check.check_id,
                "description": check.description,
                "limit": check.limit,
                "value": check.value,
                "unit": check.unit,
                "passed": check.passed,
                "action": check.action,
            }
            for check in risk_gate.checks
        ],
        "cost_model": cost_model,
        "backtest_metrics": backtest_metrics,
        "decision": {
            "action": action,
            "risk_state": risk_state,
            "reasons": decision_reasons,
            "warnings": decision_warnings,
        },
        "decision_view_id": decision_view_id,
    }
    decision_view = build_decision_view(decision_log)
    store = DecisionLogStore(paths.data_dir)
    store.append(decision_log, decision_view)


def run_signal_cycle(
    settings: AppSettings,
    max_pairs: int | None = None,
    save_csv: bool = True,
) -> pd.DataFrame:
    from datetime import datetime, timezone
    import uuid

    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        run_id = f"signal-run-{uuid.uuid4().hex[:8]}"
        as_of = datetime.now(timezone.utc)
        params = {
            "max_pairs": max_pairs,
            "intraday_marketdata": settings.strategy.intraday_marketdata,
        }
        fetch_data(settings)
        ranked = compute_pairs(
            settings,
            return_df=True,
            max_pairs=max_pairs,
            save_csv=save_csv,
        )
        if ranked is None or ranked.empty:
            return pd.DataFrame()
        ranked = ranked.copy()
        store_signal_run(session, run_id, as_of, params)
        store_signal_history(
            session,
            run_id,
            as_of,
            ranked.to_dict("records"),
        )
        # CSVs already handled by compute_pairs when save_csv is True.
        return ranked


def backfill_signal_history(
    settings: AppSettings,
    days: int,
    max_pairs: int | None = None,
    save_csv_latest: bool = True,
) -> int:
    if days <= 0:
        return 0
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    fetch_data(settings)
    today = date.today()
    stored_runs = 0
    with session_factory() as session:
        for offset in range(days):
            as_of_date = today - timedelta(days=offset)
            ranked = compute_pairs(
                settings,
                return_df=True,
                max_pairs=max_pairs,
                save_csv=save_csv_latest and offset == 0,
                as_of=as_of_date,
            )
            if ranked is None or ranked.empty:
                continue
            run_id = f"signal-run-{as_of_date:%Y%m%d}"
            if as_of_date == today:
                as_of_dt = datetime.now(timezone.utc)
            else:
                as_of_dt = datetime.combine(as_of_date, datetime.max.time()).replace(
                    tzinfo=timezone.utc
                )
            params = {
                "max_pairs": max_pairs,
                "intraday_marketdata": settings.strategy.intraday_marketdata,
                "as_of": as_of_date.isoformat(),
                "history_days": days,
            }
            store_signal_run(session, run_id, as_of_dt, params)
            delete_signal_history_run(session, run_id)
            store_signal_history(session, run_id, as_of_dt, ranked.to_dict("records"))
            stored_runs += 1
    return stored_runs
