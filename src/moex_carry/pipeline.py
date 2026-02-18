from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
import time

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
from moex_carry.strategy.spread_carry_alpha import spread_pnl_pct
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

    client = MoexIssClient(
        settings.moex.base_url,
        settings.moex.request_timeout_sec,
        max_retries=settings.moex.request_max_retries,
        retry_backoff_sec=settings.moex.request_retry_backoff_sec,
        retry_max_backoff_sec=settings.moex.request_retry_max_backoff_sec,
        fallback_ips=settings.moex.fallback_ips,
        force_fallback=settings.moex.force_fallback,
    )
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


def _minute_close_frame(raw: list[dict[str, object]], *, price_scale: float = 1.0) -> pd.DataFrame:
    df = pd.DataFrame(raw)
    if df.empty:
        return pd.DataFrame(columns=["date", "ts", "price", "volume"])
    df["ts"] = pd.to_datetime(df.get("begin"), errors="coerce").dt.floor("min")
    df["price"] = pd.to_numeric(df.get("close"), errors="coerce")
    if price_scale and price_scale != 1.0:
        df["price"] = df["price"] / price_scale
    df["volume"] = pd.to_numeric(df.get("volume"), errors="coerce").fillna(0.0)
    df = df.dropna(subset=["ts", "price"])
    if df.empty:
        return pd.DataFrame(columns=["date", "ts", "price", "volume"])
    df = df.sort_values("ts").drop_duplicates(subset=["ts"], keep="last")
    df["date"] = df["ts"].dt.date
    return df[["date", "ts", "price", "volume"]]


def _normalize_price_source(alpha_cfg: object) -> str:
    raw = getattr(alpha_cfg, "price_source", "daily_close")
    source = str(raw or "daily_close").strip().lower()
    if source not in {"daily_close", "common_minute_close"}:
        return "daily_close"
    return source


def _normalize_common_minute_anchor(alpha_cfg: object) -> str:
    raw = getattr(alpha_cfg, "common_minute_anchor", "last")
    anchor = str(raw or "last").strip().lower()
    if anchor not in {"first", "last"}:
        return "last"
    return anchor


def _fetch_minute_candles_chunked(
    client: MoexIssClient,
    *,
    engine: str,
    market: str,
    board: str,
    secid: str,
    from_date: date,
    till_date: date,
    price_scale: float,
    chunk_days: int = 10,
    chunk_retry_attempts: int = 2,
    chunk_retry_backoff_sec: float = 0.4,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    chunk = max(int(chunk_days), 1)
    retries = max(int(chunk_retry_attempts), 0)
    backoff = max(float(chunk_retry_backoff_sec), 0.0)
    day = from_date

    while day <= till_date:
        chunk_end = min(day + timedelta(days=chunk - 1), till_date)
        chunk_loaded = False
        for attempt in range(retries + 1):
            try:
                raw = client.get_candles(
                    engine,
                    market,
                    secid,
                    board,
                    day,
                    chunk_end,
                    interval=1,
                )
                chunk_df = _minute_close_frame(raw, price_scale=price_scale)
                if not chunk_df.empty:
                    frames.append(chunk_df)
                chunk_loaded = True
                break
            except Exception:
                if attempt >= retries:
                    break
                if backoff > 0:
                    wait = min(backoff * (2 ** attempt), 3.0)
                    time.sleep(wait)
        if not chunk_loaded:
            # Fallback to day-by-day calls for the failed chunk.
            fallback_day = day
            while fallback_day <= chunk_end:
                if fallback_day.weekday() >= 5:
                    fallback_day += timedelta(days=1)
                    continue
                try:
                    raw_day = client.get_candles(
                        engine,
                        market,
                        secid,
                        board,
                        fallback_day,
                        fallback_day,
                        interval=1,
                    )
                except Exception:
                    fallback_day += timedelta(days=1)
                    continue
                day_df = _minute_close_frame(raw_day, price_scale=price_scale)
                if not day_df.empty:
                    frames.append(day_df)
                fallback_day += timedelta(days=1)
        day = chunk_end + timedelta(days=1)

    if not frames:
        return pd.DataFrame(columns=["date", "ts", "price", "volume"])
    result = pd.concat(frames, ignore_index=True)
    result = result.sort_values("ts").drop_duplicates(subset=["ts"], keep="last")
    result["date"] = pd.to_datetime(result["ts"]).dt.date
    return result[["date", "ts", "price", "volume"]]


def _fetch_pair_common_minute_daily(
    client: MoexIssClient,
    *,
    settings: AppSettings,
    stock_secid: str,
    future_secid: str,
    from_date: date,
    till_date: date,
    future_scale: float,
    anchor: str,
) -> pd.DataFrame:
    stock_df = _fetch_minute_candles_chunked(
        client,
        engine=settings.moex.engine_shares,
        market=settings.moex.market_shares,
        board=settings.moex.shares_board,
        secid=stock_secid,
        from_date=from_date,
        till_date=till_date,
        price_scale=1.0,
    )
    future_df = _fetch_minute_candles_chunked(
        client,
        engine=settings.moex.engine_futures,
        market=settings.moex.market_futures,
        board=settings.moex.futures_board,
        secid=future_secid,
        from_date=from_date,
        till_date=till_date,
        price_scale=future_scale,
    )
    if stock_df.empty or future_df.empty:
        return pd.DataFrame(columns=["date", "spot", "future", "spot_volume", "future_volume", "exec_ts"])

    joined = stock_df.merge(
        future_df,
        on="ts",
        how="inner",
        suffixes=("_stock", "_future"),
    )
    if joined.empty:
        return pd.DataFrame(columns=["date", "spot", "future", "spot_volume", "future_volume", "exec_ts"])
    joined = joined.sort_values("ts")
    joined["date"] = pd.to_datetime(joined["ts"]).dt.date

    per_day_vol = (
        stock_df.groupby("date", as_index=False)["volume"].sum().rename(columns={"volume": "spot_volume"})
    ).merge(
        future_df.groupby("date", as_index=False)["volume"].sum().rename(columns={"volume": "future_volume"}),
        on="date",
        how="inner",
    )

    selected = joined.groupby("date", as_index=False).head(1) if anchor == "first" else joined.groupby("date", as_index=False).tail(1)
    selected = selected.merge(per_day_vol, on="date", how="left")
    selected = selected.rename(
        columns={
            "price_stock": "spot",
            "price_future": "future",
            "ts": "exec_ts",
        }
    )
    selected = selected[["date", "spot", "future", "spot_volume", "future_volume", "exec_ts"]]
    selected = selected.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return selected


def _fetch_pair_price_history(
    client: MoexIssClient,
    *,
    settings: AppSettings,
    stock_secid: str,
    future_secid: str,
    from_date: date,
    till_date: date,
    future_scale: float,
    alpha_cfg: object,
) -> pd.DataFrame:
    source = _normalize_price_source(alpha_cfg)
    if source == "common_minute_close":
        return _fetch_pair_common_minute_daily(
            client,
            settings=settings,
            stock_secid=stock_secid,
            future_secid=future_secid,
            from_date=from_date,
            till_date=till_date,
            future_scale=future_scale,
            anchor=_normalize_common_minute_anchor(alpha_cfg),
        )

    stock_candles = _fetch_candles(
        client,
        settings.moex.engine_shares,
        settings.moex.market_shares,
        settings.moex.shares_board,
        stock_secid,
        from_date,
        till_date,
    )
    future_candles = _fetch_candles(
        client,
        settings.moex.engine_futures,
        settings.moex.market_futures,
        settings.moex.futures_board,
        future_secid,
        from_date,
        till_date,
        price_scale=future_scale,
    )
    if stock_candles.empty or future_candles.empty:
        return pd.DataFrame(columns=["date", "spot", "future", "spot_volume", "future_volume"])
    merged = pd.merge(stock_candles, future_candles, on="date", how="inner")
    if merged.empty:
        return pd.DataFrame(columns=["date", "spot", "future", "spot_volume", "future_volume"])
    merged.rename(
        columns={
            stock_secid: "spot",
            future_secid: "future",
            f"{stock_secid}_volume": "spot_volume",
            f"{future_secid}_volume": "future_volume",
        },
        inplace=True,
    )
    return merged


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
) -> tuple[bool, list[str], dict[str, object]]:
    reasons: list[str] = []
    warnings: list[str] = []
    stock_imbalance = _depth_imbalance_ratio(stock_bid_depth, stock_ask_depth)
    fut_imbalance = _depth_imbalance_ratio(fut_bid_depth, fut_ask_depth)
    stock_min_depth = _min_depth(stock_bid_depth, stock_ask_depth)
    fut_min_depth = _min_depth(fut_bid_depth, fut_ask_depth)
    stock_quote_available = spot_bid is not None and spot_ask is not None
    fut_quote_available = fut_bid is not None and fut_ask is not None
    stock_depth_available = stock_min_depth is not None
    fut_depth_available = fut_min_depth is not None

    if use_intraday:
        if not stock_quote_available:
            warnings.append("orderbook_stock_quote_missing")
        if not fut_quote_available:
            warnings.append("orderbook_fut_quote_missing")
        if not stock_depth_available:
            warnings.append("orderbook_stock_depth_missing")
        if not fut_depth_available:
            warnings.append("orderbook_fut_depth_missing")

    if bool(getattr(alpha_cfg, "require_live_orderbook_for_entry", False)):
        if not use_intraday:
            reasons.append("orderbook_intraday_disabled")
        if not stock_quote_available:
            reasons.append("orderbook_stock_missing")
        if not fut_quote_available:
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

    metrics: dict[str, object] = {
        "orderbook_pass": len(reasons) == 0,
        "orderbook_stock_min_depth": stock_min_depth,
        "orderbook_fut_min_depth": fut_min_depth,
        "orderbook_stock_imbalance": stock_imbalance,
        "orderbook_fut_imbalance": fut_imbalance,
        "orderbook_stock_quote_age_sec": stock_quote_age_sec,
        "orderbook_fut_quote_age_sec": fut_quote_age_sec,
        "orderbook_stock_quote_available": stock_quote_available,
        "orderbook_fut_quote_available": fut_quote_available,
        "orderbook_stock_depth_available": stock_depth_available,
        "orderbook_fut_depth_available": fut_depth_available,
        "orderbook_data_warnings": warnings,
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


def _resolve_spread_tolerance(alpha_cfg: object, fallback: float) -> float:
    raw_value = getattr(alpha_cfg, "entry_spread_tolerance_pct", None)
    try:
        value = float(raw_value) if raw_value is not None else float(fallback)
    except (TypeError, ValueError):
        value = float(fallback)
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
    spread_tolerance = _resolve_spread_tolerance(alpha_cfg, entry_tolerance)
    stock_target = float(spot_mid)
    future_target = float(future_mid)
    spread_target = float(spread_mid_value)
    direction_norm = "reverse" if str(direction).lower() == "reverse" else "cash_and_carry"

    spread_band = max(abs(spread_target), 1.0) * spread_tolerance
    spread_pct_band = spread_band / abs(stock_target) if stock_target != 0 else spread_tolerance

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
        "entry_spread_tolerance_pct": spread_tolerance,
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
    exit_forced = (
        series_df["exit_forced"]
        if "exit_forced" in series_df.columns
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
    *,
    initial_state: dict[str, object] | None = None,
    return_state: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, object]]:
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

    series_dates = [_as_date(value) for value in series_df["date"]]
    series_exec_ts = [
        _row_exec_timestamp(
            series_dates[idx],
            series_df.at[idx, "exec_ts"] if "exec_ts" in series_df.columns else None,
        )
        for idx in range(n)
    ]
    spreads_pct = series_df["spread_pct"].tolist()
    state_payload = initial_state if isinstance(initial_state, dict) else {}
    spread_history_raw = state_payload.get("spread_history")
    spread_history: list[float] = []
    if isinstance(spread_history_raw, list):
        for item in spread_history_raw:
            try:
                spread_history.append(float(item))
            except (TypeError, ValueError):
                continue

    def _restore_state_mapping(value: object) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        restored: dict[str, object] = {}
        for key, item in value.items():
            if key.endswith("_ts"):
                restored_ts = _as_naive_datetime(item)
                restored[key] = restored_ts if restored_ts is not None else item
            elif key.endswith("_day"):
                try:
                    restored[key] = _as_date(item)
                except Exception:
                    restored[key] = item
            else:
                restored[key] = item
        return restored

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

    pending_entry = _restore_state_mapping(state_payload.get("pending_entry"))
    pending_exit = _restore_state_mapping(state_payload.get("pending_exit"))
    open_position = _restore_state_mapping(state_payload.get("open_position"))
    try:
        current_cycle = int(state_payload.get("current_cycle") or 0)
    except (TypeError, ValueError):
        current_cycle = 0

    for idx in range(n):
        row = series_df.iloc[idx]
        row_date = series_dates[idx]
        row_ts = series_exec_ts[idx]
        spot_mid = float(row["spot_mid"])
        future_mid = float(row["future_mid"])
        spread_mid_value = float(row.get("spread_mid", 0.0))

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

        try:
            spread_history.append(float(spreads_pct[idx]))
        except (TypeError, ValueError):
            spread_history.append(0.0)
        z = 0.0
        entry_filter_ok = True
        if alpha_cfg.z_entry_threshold is not None:
            z = zscore(spread_history, window=alpha_cfg.z_window, min_window=10)
            entry_filter_ok = z <= alpha_cfg.z_entry_threshold

        spread_entry_exec_value = spread_entry_exec(
            exec_prices.stock_buy, float(row.get("pv_div", 0.0)), exec_prices.fut_sell
        )
        spread_exit_exec_value = spread_exit_exec(
            exec_prices.stock_sell, float(row.get("pv_div", 0.0)), exec_prices.fut_buy
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
                if row_ts > deadline_ts:
                    if 0 <= signal_idx < n:
                        entry_fill_statuses[signal_idx] = "entry_unfilled"
                        unfilled_reasons[signal_idx] = "entry_timeout"
                    pending_entry = None
                elif row_ts >= submit_ts and _execution_band_ok(
                    target_spot=float(pending_entry["target_spot"]),
                    target_future=float(pending_entry["target_future"]),
                    target_spread=float(pending_entry["target_spread"]),
                    spot_now=spot_mid,
                    future_now=future_mid,
                    spread_now=spread_mid_value,
                    tolerance=entry_tolerance,
                ):
                    direction = str(pending_entry.get("direction", "cash_and_carry"))
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
                        if 0 <= target_idx < n:
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
                timed_out = row_ts > deadline_ts
                band_ok = _execution_band_ok(
                    target_spot=float(pending_exit["target_spot"]),
                    target_future=float(pending_exit["target_future"]),
                    target_spread=float(pending_exit["target_spread"]),
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
                    direction = str(open_position.get("direction", "cash_and_carry"))
                    if direction == "reverse":
                        exit_spot_exec = float(exec_prices.stock_buy) * (1.0 + penalty)
                        exit_fut_exec = float(exec_prices.fut_sell) * (1.0 - penalty)
                        exit_spread_value = spread_pct_entry_exec
                    else:
                        exit_spot_exec = float(exec_prices.stock_sell) * (1.0 - penalty)
                        exit_fut_exec = float(exec_prices.fut_buy) * (1.0 + penalty)
                        exit_spread_value = spread_pct_exit_exec

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
                            + float(stock_fee)
                            + float(fut_fee)
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
                            if 0 <= target_idx < n:
                                exit_signal_days[target_idx] = str(pending_exit["signal_day"])
                                exit_submit_tss[target_idx] = _iso_or_none(submit_ts)
                                exit_fill_tss[target_idx] = _iso_or_none(row_ts)
                                exit_wait_minutes[target_idx] = wait_mins
                                exit_fill_statuses[target_idx] = "forced" if forced else "filled"
                                exit_forced_flags[target_idx] = forced
                        if forced:
                            if 0 <= signal_idx < n:
                                unfilled_reasons[signal_idx] = "exit_timeout_forced"
                            unfilled_reasons[idx] = "exit_timeout_forced"

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
        if 0 <= signal_idx < n and entry_fill_statuses[signal_idx] in {None, "pending"}:
            entry_fill_statuses[signal_idx] = "entry_unfilled"
            unfilled_reasons[signal_idx] = unfilled_reasons[signal_idx] or "entry_no_fill_in_window"

    if pending_exit is not None:
        signal_idx = int(pending_exit["signal_index"])
        if 0 <= signal_idx < n and exit_fill_statuses[signal_idx] in {None, "pending"}:
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
    if not return_state:
        return series_df
    state_out = {
        "pending_entry": pending_entry,
        "pending_exit": pending_exit,
        "open_position": open_position,
        "current_cycle": int(current_cycle),
        "spread_history": spread_history[-2048:],
        "last_processed_exec_ts": _iso_or_none(series_exec_ts[-1]) if series_exec_ts else None,
    }
    return series_df, state_out

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


def build_spread_series(
    settings: AppSettings,
    stock_secid: str,
    future_secid: str,
    window_days: int = 60,
    full_life: bool = False,
) -> pd.DataFrame:
    paths = resolve_paths(settings)
    dirs = _data_paths(paths.data_dir)
    alpha_cfg = settings.spread_carry_alpha
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
    client = MoexIssClient(
        settings.moex.base_url,
        settings.moex.request_timeout_sec,
        max_retries=settings.moex.request_max_retries,
        retry_backoff_sec=settings.moex.request_retry_backoff_sec,
        retry_max_backoff_sec=settings.moex.request_retry_max_backoff_sec,
        fallback_ips=settings.moex.fallback_ips,
        force_fallback=settings.moex.force_fallback,
    )
    merged = _fetch_pair_price_history(
        client,
        settings=settings,
        stock_secid=stock_secid,
        future_secid=future_secid,
        from_date=lookback,
        till_date=today,
        future_scale=future_scale,
        alpha_cfg=alpha_cfg,
    )
    if merged.empty:
        return pd.DataFrame()

    dividends = _load_dividends(client, stock_secid, paths.data_dir)
    key_rates = _load_key_rates(dirs["raw"] / "key_rates.csv")
    series_df = compute_spread_series(
        merged[["date", "spot", "future"]].rename(columns={"future": "future_price"}),
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
    client = MoexIssClient(
        settings.moex.base_url,
        settings.moex.request_timeout_sec,
        max_retries=settings.moex.request_max_retries,
        retry_backoff_sec=settings.moex.request_retry_backoff_sec,
        retry_max_backoff_sec=settings.moex.request_retry_max_backoff_sec,
        fallback_ips=settings.moex.fallback_ips,
        force_fallback=settings.moex.force_fallback,
    )

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
        future_spec = future_spec_map.get(mapping.future_secid)
        if future_spec is None:
            continue
        future_scale = _future_price_scale(future_spec)
        merged = _fetch_pair_price_history(
            client,
            settings=settings,
            stock_secid=mapping.stock_secid,
            future_secid=mapping.future_secid,
            from_date=lookback,
            till_date=as_of_date,
            future_scale=future_scale,
            alpha_cfg=alpha_cfg,
        )
        if merged.empty:
            continue
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
        avg_trade_return_annual_operational = _avg_recent_trade_return_annual_operational(
            series_with_signals
        )
        execution_stats = _execution_quality_stats(series_with_signals)

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
            "orderbook_stock_quote_available": orderbook_metrics["orderbook_stock_quote_available"],
            "orderbook_fut_quote_available": orderbook_metrics["orderbook_fut_quote_available"],
            "orderbook_stock_depth_available": orderbook_metrics["orderbook_stock_depth_available"],
            "orderbook_fut_depth_available": orderbook_metrics["orderbook_fut_depth_available"],
            "orderbook_data_warnings": orderbook_metrics["orderbook_data_warnings"],
            "avg_trade_return_annual_recent": avg_trade_return_annual,
            "avg_trade_return_annual_operational_recent": avg_trade_return_annual_operational,
            "share_target_pass": execution_stats["share_target_pass"],
            "unfilled_entry_rate": execution_stats["unfilled_entry_rate"],
            "unfilled_exit_rate": execution_stats["unfilled_exit_rate"],
            "forced_exit_rate": execution_stats["forced_exit_rate"],
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
                "orderbook_stock_quote_available": orderbook_metrics["orderbook_stock_quote_available"],
                "orderbook_fut_quote_available": orderbook_metrics["orderbook_fut_quote_available"],
                "orderbook_stock_depth_available": orderbook_metrics["orderbook_stock_depth_available"],
                "orderbook_fut_depth_available": orderbook_metrics["orderbook_fut_depth_available"],
                "orderbook_data_warnings": orderbook_metrics["orderbook_data_warnings"],
                "dollar_vol_stock": dollar_vol_stock,
                "dollar_vol_fut": dollar_vol_fut,
                "days_to_exit": days_exit,
                "open_interest": open_interest,
                "r_cb_annual": r_cb,
                "r_fund_annual": r_fund,
                "r_disc_annual": r_disc,
                "avg_trade_return_annual_recent": avg_trade_return_annual,
                "avg_trade_return_annual_operational_recent": avg_trade_return_annual_operational,
                "share_target_pass": execution_stats["share_target_pass"],
                "unfilled_entry_rate": execution_stats["unfilled_entry_rate"],
                "unfilled_exit_rate": execution_stats["unfilled_exit_rate"],
                "forced_exit_rate": execution_stats["forced_exit_rate"],
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
    ranked = score_pairs_alpha(
        metrics_df,
        primary_metric=getattr(
            settings.spread_carry_alpha,
            "ranking_primary_metric",
            "avg_trade_return_annual_operational_recent",
        ),
    )
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
                "avg_trade_return_annual_recent",
                "avg_trade_return_annual_operational_recent",
                "share_target_pass",
                "unfilled_entry_rate",
                "unfilled_exit_rate",
                "forced_exit_rate",
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
    client = MoexIssClient(
        settings.moex.base_url,
        settings.moex.request_timeout_sec,
        max_retries=settings.moex.request_max_retries,
        retry_backoff_sec=settings.moex.request_retry_backoff_sec,
        retry_max_backoff_sec=settings.moex.request_retry_max_backoff_sec,
        fallback_ips=settings.moex.fallback_ips,
        force_fallback=settings.moex.force_fallback,
    )
    today = date.today()
    lookback_days = max(settings.data.backtest_lookback_days, 1)
    lookback = today - timedelta(days=lookback_days)
    alpha_cfg = settings.spread_carry_alpha
    merged = _fetch_pair_price_history(
        client,
        settings=settings,
        stock_secid=stock_secid,
        future_secid=future_secid,
        from_date=lookback,
        till_date=today,
        future_scale=future_scale,
        alpha_cfg=alpha_cfg,
    )
    if merged.empty:
        return None

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
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
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
    store = DecisionLogStore(paths.data_dir, session_factory=session_factory)
    store.append(decision_log, decision_view)


def run_signal_cycle(
    settings: AppSettings,
    max_pairs: int | None = None,
    save_csv: bool = True,
) -> pd.DataFrame:
    if settings.ui.use_unified_signal_engine:
        paths = resolve_paths(settings)
        _ensure_reference_data(settings)
        resolved_max_pairs = _resolve_unified_max_pairs(settings, max_pairs)
        ingest_cycle = _run_unified_incremental_ingest(
            settings,
            data_dir=paths.data_dir,
            max_pairs=resolved_max_pairs,
        )
        snapshot = _build_unified_snapshot(
            settings=settings,
            data_dir=paths.data_dir,
            max_pairs=resolved_max_pairs,
            as_of=None,
            ingest_cycle=ingest_cycle,
        )
        ranked = snapshot.signals.copy()
        if ranked.empty:
            return pd.DataFrame()
        if save_csv:
            from moex_carry.ui.unified_runtime import persist_snapshot_to_csv

            persist_snapshot_to_csv(snapshot, paths.data_dir)

        import uuid

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            run_id = f"signal-run-{uuid.uuid4().hex[:8]}"
            as_of_dt = datetime.now(timezone.utc)
            params = {
                "max_pairs": max_pairs,
                "max_pairs_resolved": resolved_max_pairs,
                "intraday_marketdata": settings.strategy.intraday_marketdata,
                "engine": "unified_minute_replay",
                "signals_total": int(len(ranked)),
                "warnings": list(snapshot.warnings),
                "errors": list(snapshot.errors),
            }
            if ingest_cycle is not None:
                params["ingest_degraded"] = bool(getattr(ingest_cycle, "degraded", False))
                params["data_watermark_before"] = getattr(ingest_cycle, "global_watermark_before", None)
                params["data_watermark_after"] = getattr(ingest_cycle, "global_watermark_after", None)
            store_signal_run(session, run_id, as_of_dt, params)
            store_signal_history(
                session,
                run_id,
                as_of_dt,
                ranked.to_dict("records"),
            )
        return ranked

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

    if settings.ui.use_unified_signal_engine:
        paths = resolve_paths(settings)
        _ensure_reference_data(settings)
        resolved_max_pairs = _resolve_unified_max_pairs(settings, max_pairs)
        ingest_cycle = _run_unified_incremental_ingest(
            settings,
            data_dir=paths.data_dir,
            max_pairs=resolved_max_pairs,
        )
        from moex_carry.ui.unified_runtime import persist_snapshot_to_csv

        engine = create_engine_from_settings(settings)
        init_db(engine)
        session_factory = create_session_factory(engine)
        today = date.today()
        stored_runs = 0
        with session_factory() as session:
            for offset in range(days):
                as_of_date = today - timedelta(days=offset)
                snapshot = _build_unified_snapshot(
                    settings=settings,
                    data_dir=paths.data_dir,
                    max_pairs=resolved_max_pairs,
                    as_of=as_of_date,
                    ingest_cycle=ingest_cycle if offset == 0 else None,
                )
                ranked = snapshot.signals.copy()
                if ranked.empty:
                    continue
                if save_csv_latest and offset == 0:
                    persist_snapshot_to_csv(snapshot, paths.data_dir)
                run_id = f"signal-run-{as_of_date:%Y%m%d}"
                if as_of_date == today:
                    as_of_dt = datetime.now(timezone.utc)
                else:
                    as_of_dt = datetime.combine(as_of_date, datetime.max.time()).replace(
                        tzinfo=timezone.utc
                    )
                params = {
                    "max_pairs": max_pairs,
                    "max_pairs_resolved": resolved_max_pairs,
                    "intraday_marketdata": settings.strategy.intraday_marketdata,
                    "engine": "unified_minute_replay",
                    "as_of": as_of_date.isoformat(),
                    "history_days": days,
                    "signals_total": int(len(ranked)),
                    "warnings": list(snapshot.warnings),
                    "errors": list(snapshot.errors),
                }
                if offset == 0 and ingest_cycle is not None:
                    params["ingest_degraded"] = bool(getattr(ingest_cycle, "degraded", False))
                    params["data_watermark_before"] = getattr(ingest_cycle, "global_watermark_before", None)
                    params["data_watermark_after"] = getattr(ingest_cycle, "global_watermark_after", None)
                store_signal_run(session, run_id, as_of_dt, params)
                delete_signal_history_run(session, run_id)
                store_signal_history(session, run_id, as_of_dt, ranked.to_dict("records"))
                stored_runs += 1
        return stored_runs

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


REFERENCE_DATA_MAX_AGE_HOURS = 12.0


def _resolve_unified_max_pairs(settings: AppSettings, max_pairs: int | None) -> int | None:
    if max_pairs is not None:
        configured = int(max_pairs)
        return configured if configured > 0 else None
    strategy_max = int(settings.strategy.max_pairs or 0)
    return strategy_max if strategy_max > 0 else None


def _resolve_incremental_checkpoint_root(settings: AppSettings, data_dir: Path) -> Path:
    configured = Path(str(getattr(settings.ui, "incremental_checkpoint_dir", "./data/state/incremental_replay")))
    if configured.is_absolute():
        return configured
    text = str(configured).replace("\\", "/")
    if text.startswith("./data/"):
        return data_dir.parent / text[2:]
    if text.startswith("data/"):
        return data_dir.parent / text
    return data_dir / configured


def _ensure_reference_data(settings: AppSettings) -> None:
    paths = resolve_paths(settings)
    dirs = _data_paths(paths.data_dir)
    required = [
        dirs["raw"] / "shares.csv",
        dirs["raw"] / "futures.csv",
        dirs["raw"] / "key_rates.csv",
    ]
    if _reference_data_stale(required, max_age_hours=REFERENCE_DATA_MAX_AGE_HOURS):
        fetch_data(settings)


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
    from moex_carry.ui.unified_runtime import list_unified_ingest_pairs

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
    from moex_carry.ui.unified_runtime import build_unified_market_snapshot

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
