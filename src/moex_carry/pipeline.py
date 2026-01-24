from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from moex_carry.analytics.carry import fair_value, implied_rate, pv_dividends
from moex_carry.analytics.stats import spread_stats
from moex_carry.config import AppSettings, resolve_paths
from moex_carry.costs.engine import CostProfile, costs_as_annual_rate, total_cost_bps
from moex_carry.costs.taxes import TaxProfile
from moex_carry.data import CbrKeyRateClient, MoexIssClient
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.data.dividends import apply_overrides, load_dividends
from moex_carry.decision_log import DecisionLogStore, build_decision_view, build_snapshot
from moex_carry.domain.decision import NewsItem, RiskProfile
from moex_carry.domain.models import ContractSpec, DividendEvent, Instrument, KeyRate
from moex_carry.selection.ranking import score_pairs
from moex_carry.selection.universe import build_pair_mappings
from moex_carry.strategy.news_filter import apply_news_filter
from moex_carry.strategy.overall_strategy import aggregate_strategy_signals, strategy_signal_to_dict
from moex_carry.strategy.orchestrator import build_portfolio_proposal, generate_signal
from moex_carry.strategy.risk_gate import evaluate_risk_profile
from moex_carry.strategy.spread_cycle import SpreadCycleState, update_spread_cycle
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


def compute_spread_series(
    prices: pd.DataFrame,
    expiry: date,
    dividends: list[DividendEvent],
    key_rates: list[KeyRate],
    z_window: int = 60,
    z_min_window: int = 10,
    z_entry: float = 2.0,
    z_exit: float = 0.5,
) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    series_rows = []
    spread_values: list[float] = []
    for _, row in prices.iterrows():
        row_date = pd.to_datetime(row["date"]).date()
        spot = float(row["spot"])
        future_price = float(row["future_price"])
        time_years = max((expiry - row_date).days / 365.0, 0.0)
        key_rate_row = latest_rate(key_rates, row_date)
        key_rate_value = key_rate_row.rate if key_rate_row else 0.0
        pv_div = pv_dividends(dividends, row_date, expiry, key_rate_value)
        fair = fair_value(spot, pv_div, key_rate_value, time_years)
        spread = future_price - fair
        spread_values.append(spread)
        series_rows.append(
            {
                "date": row_date,
                "spot": spot,
                "future_price": future_price,
                "fair_value": fair,
                "spread": spread,
            }
        )
    for idx in range(len(series_rows)):
        stats = spread_stats(spread_values[: idx + 1], window=z_window, min_window=z_min_window)
        series_rows[idx]["zscore"] = stats["trend_zscore"]
        series_rows[idx]["z_entry"] = z_entry
        series_rows[idx]["z_exit"] = z_exit
    return pd.DataFrame(series_rows)


def build_spread_series(
    settings: AppSettings,
    stock_secid: str,
    future_secid: str,
    window_days: int = 60,
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
    merged.rename(columns={stock_secid: "spot", future_secid: "future_price"}, inplace=True)

    dividends = _load_dividends(client, stock_secid, paths.data_dir)
    key_rates = _load_key_rates(dirs["raw"] / "key_rates.csv")
    series_df = compute_spread_series(
        merged[["date", "spot", "future_price"]],
        future_spec.expiry,
        dividends,
        key_rates,
        z_window=settings.strategy.z_window,
        z_min_window=settings.strategy.z_min_window,
        z_entry=settings.strategy.z_entry,
        z_exit=settings.strategy.z_exit,
    )
    if series_df.empty:
        return series_df

    cost_profile = CostProfile(
        stock_commission_bps=settings.costs.stock_commission_bps,
        futures_commission_bps=settings.costs.futures_commission_bps,
        exchange_fee_bps=settings.costs.exchange_fee_bps,
        slippage_bps=settings.costs.slippage_bps,
    )
    spreads = series_df["spread"].tolist()
    signal_actions: list[str] = []
    signal_directions: list[str | None] = []
    entry_flags: list[bool] = []
    exit_flags: list[bool] = []
    entry_cycles: list[int | None] = []
    exit_cycles: list[int | None] = []
    cycle_ids: list[int | None] = []
    cycle_returns: list[float | None] = []
    implied_series: list[float] = []
    required_series: list[float] = []
    cycle_state = SpreadCycleState()

    for idx, row in series_df.iterrows():
        row_date = row["date"]
        spot = float(row["spot"])
        future_price = float(row["future_price"])
        time_years = max((future_spec.expiry - row_date).days / 365.0, 0.0)
        key_rate_row = latest_rate(key_rates, row_date)
        key_rate_value = key_rate_row.rate if key_rate_row else 0.0
        pv_div = pv_dividends(dividends, row_date, future_spec.expiry, key_rate_value)
        implied = implied_rate(future_price, spot, pv_div, time_years)
        implied_net = implied - costs_as_annual_rate(cost_profile, time_years)
        required_rate = key_rate_value + settings.strategy.term_premium_base + (
            settings.strategy.term_premium_slope * time_years
        )
        days_to_expiry = (future_spec.expiry - row_date).days
        days_to_exdiv = min(
            [
                (event.ex_date - row_date).days
                for event in dividends
                if event.ex_date >= row_date
            ]
            or [9999]
        )

        signal = generate_signal(
            spread_series=spreads[: idx + 1],
            implied_rate_net=implied_net,
            required_rate=required_rate,
            days_to_expiry=days_to_expiry,
            days_to_exdiv=days_to_exdiv,
            z_window=settings.strategy.z_window,
            z_min_window=settings.strategy.z_min_window,
            z_entry=settings.strategy.z_entry,
            z_exit=settings.strategy.z_exit,
            implied_rate_buffer=settings.strategy.implied_rate_buffer,
            min_days_to_expiry=settings.strategy.min_days_to_expiry,
            min_days_to_exdiv=settings.strategy.min_days_to_exdiv,
        )
        cycle_update = update_spread_cycle(
            cycle_state,
            signal.action,
            signal.direction,
            spreads[idx],
            spot,
        )

        signal_actions.append(signal.action)
        signal_directions.append(signal.direction)
        entry_flags.append(cycle_update.entry_flag)
        exit_flags.append(cycle_update.exit_flag)
        entry_cycles.append(cycle_update.entry_cycle)
        exit_cycles.append(cycle_update.exit_cycle)
        cycle_ids.append(cycle_update.cycle_id)
        cycle_returns.append(cycle_update.cycle_return_pct)
        implied_series.append(implied_net)
        required_series.append(required_rate)

    series_df["signal_action"] = signal_actions
    series_df["signal_direction"] = signal_directions
    series_df["entry_flag"] = entry_flags
    series_df["exit_flag"] = exit_flags
    series_df["entry_cycle"] = entry_cycles
    series_df["exit_cycle"] = exit_cycles
    series_df["cycle_id"] = cycle_ids
    series_df["cycle_return_pct"] = cycle_returns
    series_df["implied_rate_net"] = implied_series
    series_df["required_rate"] = required_series
    return series_df


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

    as_of_date = as_of or date.today()
    lookback_days = max(settings.data.compute_lookback_days, 1)
    lookback = as_of_date - timedelta(days=lookback_days)
    results = []

    cost_profile = CostProfile(
        stock_commission_bps=settings.costs.stock_commission_bps,
        futures_commission_bps=settings.costs.futures_commission_bps,
        exchange_fee_bps=settings.costs.exchange_fee_bps,
        slippage_bps=settings.costs.slippage_bps,
    )

    limit = max_pairs if max_pairs is not None else settings.strategy.max_pairs
    selected = mappings if limit == 0 else mappings[: max(limit, 1)]
    for mapping in selected:
        expiry = mapping.expiry
        if expiry <= as_of_date:
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
        future_scale = _future_price_scale(future_spec_map.get(mapping.future_secid))
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
        if as_of is not None and latest["date"] != as_of_date:
            continue
        as_of = latest["date"]
        snapshot_payload = merged.to_csv(index=False).encode("utf-8")
        snapshot = build_snapshot(
            source="MOEX_ISS",
            instrument=f"{mapping.stock_secid}-{mapping.future_secid}",
            as_of=as_of,
            payload=snapshot_payload,
            is_cached=False,
        )

        dividends = _load_dividends(client, mapping.stock_secid, paths.data_dir)
        fair_series: list[float] = []
        spread_series: list[float] = []
        for _, row in merged.iterrows():
            row_date = row["date"]
            spot_row = float(row["spot"])
            future_row = float(row["future"])
            time_years_row = max((expiry - row_date).days / 365.0, 0.0)
            key_rate_row = latest_rate(key_rates, row_date)
            key_rate_value_row = key_rate_row.rate if key_rate_row else 0.0
            pv_div_row = pv_dividends(dividends, row_date, expiry, key_rate_value_row)
            fair_row = fair_value(spot_row, pv_div_row, key_rate_value_row, time_years_row)
            fair_series.append(fair_row)
            spread_series.append(future_row - fair_row)

        spot = float(latest["spot"])
        future = float(latest["future"])
        use_intraday = settings.strategy.intraday_marketdata and (
            as_of is None or as_of_date == date.today()
        )
        if use_intraday:
            stock_quotes = client.get_marketdata(
                settings.moex.engine_shares,
                settings.moex.market_shares,
                settings.moex.shares_board,
                mapping.stock_secid,
            )
            if stock_quotes:
                last_quote = stock_quotes[0]
                quote_value = last_quote.get("LAST") or last_quote.get("LCLOSE") or last_quote.get("OPEN")
                if quote_value:
                    spot = float(quote_value)
            future_quotes = client.get_marketdata(
                settings.moex.engine_futures,
                settings.moex.market_futures,
                settings.moex.futures_board,
                mapping.future_secid,
            )
            if future_quotes:
                last_quote = future_quotes[0]
                quote_value = last_quote.get("LAST") or last_quote.get("LCLOSE") or last_quote.get("OPEN")
                if quote_value:
                    future_value = float(quote_value)
                    future = (
                        future_value / future_scale if future_scale and future_scale > 0 else future_value
                    )
        time_years = max((expiry - as_of).days / 365.0, 0.0)
        key_rate = latest_rate(key_rates, as_of)
        key_rate_value = key_rate.rate if key_rate else 0.0
        pv_div = pv_dividends(dividends, as_of, expiry, key_rate_value)
        fair = fair_value(spot, pv_div, key_rate_value, time_years)
        if fair_series:
            fair_series[-1] = fair
        if spread_series:
            spread_series[-1] = future - fair
        implied = implied_rate(future, spot, pv_div, time_years)
        implied_net = implied - costs_as_annual_rate(cost_profile, time_years)
        stats = spread_stats(
            spread_series,
            window=settings.strategy.z_window,
            min_window=settings.strategy.z_min_window,
        )
        z = stats["trend_zscore"]
        spread_vol = stats["std"]
        spread_vol_pct = spread_vol / max(abs(spot), 1e-6)
        trend_pos = stats["trend_pos"]
        trend_slope = stats["trend_slope"]
        trend_z = stats["trend_zscore"]

        days_to_expiry = (expiry - as_of).days
        days_to_exdiv = min(
            [(event.ex_date - as_of).days for event in dividends if event.ex_date >= as_of] or [9999]
        )
        required_rate = key_rate_value + settings.strategy.term_premium_base + (
            settings.strategy.term_premium_slope * time_years
        )
        z_entry = settings.strategy.z_entry
        implied_buffer = settings.strategy.implied_rate_buffer
        z_component = abs(z) / z_entry if z_entry else 0.0
        rate_gap = abs(implied_net - required_rate)
        rate_component = rate_gap / implied_buffer if implied_buffer else 0.0
        signal_score_norm = 0.5 * (z_component + rate_component)
        signal = generate_signal(
            spread_series=spread_series,
            implied_rate_net=implied_net,
            required_rate=required_rate,
            days_to_expiry=days_to_expiry,
            days_to_exdiv=days_to_exdiv,
            z_window=settings.strategy.z_window,
            z_min_window=settings.strategy.z_min_window,
            z_entry=settings.strategy.z_entry,
            z_exit=settings.strategy.z_exit,
            implied_rate_buffer=settings.strategy.implied_rate_buffer,
            min_days_to_expiry=settings.strategy.min_days_to_expiry,
            min_days_to_exdiv=settings.strategy.min_days_to_exdiv,
        )
        signal_reasons = signal.reasons
        signal_metrics = signal.metrics
        stock_name = instrument_map.get(mapping.stock_secid).name if mapping.stock_secid in instrument_map else mapping.stock_secid
        results.append(
            {
                "stock": mapping.stock_secid,
                "stock_name": stock_name,
                "future": mapping.future_secid,
                "expiry": expiry,
                "spot": spot,
                "future_price": future,
                "fair_value": fair,
                "spread": future - fair,
                "zscore": z,
                "zscore_raw": stats["zscore"],
                "spread_vol": spread_vol,
                "spread_vol_pct": spread_vol_pct,
                "spread_trend_pos": trend_pos,
                "spread_trend_slope": trend_slope,
                "spread_trend_z": trend_z,
                "implied_rate_net": implied_net,
                "required_rate": required_rate,
                "expected_net_irr": implied_net,
                "signal_action": signal.action,
                "signal_direction": signal.direction,
                "signal_score": signal.score,
                "signal_score_norm": signal_score_norm,
                "signal_reasons": signal_reasons,
                "signal_metrics": signal_metrics,
                "snapshot_id": snapshot["snapshot_id"],
                "snapshot_hash": snapshot["hash"],
                "snapshot_as_of": snapshot["as_of"],
            }
        )

    if not results:
        return pd.DataFrame() if return_df else None
    metrics_df = pd.DataFrame(results)
    ranked = score_pairs(metrics_df)
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
                "implied_rate_net",
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
    future_scale = _future_price_scale(future_spec_map.get(future_secid))
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
    result = backtest_pair(
        prices=merged[["date", "spot", "future"]],
        expiry=expiry,
        dividends=dividends,
        key_rates=key_rates,
        costs=cost_profile,
        taxes=tax_profile,
        strategy_config=settings.strategy,
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
        {"name": "spread", "value": float(top.get("spread", 0.0)), "units": "price"},
        {"name": "zscore", "value": float(top.get("zscore", 0.0)), "units": "z"},
        {
            "name": "implied_rate_net",
            "value": float(top.get("implied_rate_net", 0.0)),
            "units": "rate",
        },
        {
            "name": "required_rate",
            "value": float(top.get("required_rate", 0.0)),
            "units": "rate",
        },
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
        "name": "carry_spread",
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
    expected_return_raw = top.get("expected_net_irr", None)
    expected_return = (
        float(expected_return_raw) if pd.notna(expected_return_raw) else None
    )
    spread_payload = {
        "strategy_id": "carry_spread",
        "strategy_type": "arbitrage",
        "cadence": settings.aggregation.rebalance_cadence,
        "horizon": "short",
        "action": signal_action,
        "confidence": min(abs(signal_score), 1.0),
        "expected_return": expected_return,
        "risk_estimate": float(top.get("zscore", 0.0)) if pd.notna(top.get("zscore")) else None,
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
            "spread": float(top.get("spread", 0.0)) if pd.notna(top.get("spread")) else None,
            "zscore": float(top.get("zscore", 0.0)) if pd.notna(top.get("zscore")) else None,
            "implied_rate_net": float(top.get("implied_rate_net", 0.0))
            if pd.notna(top.get("implied_rate_net"))
            else None,
            "required_rate": float(top.get("required_rate", 0.0))
            if pd.notna(top.get("required_rate"))
            else None,
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
                "name": "carry_spread",
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
