import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from moex_carry.analytics.carry import fair_value, implied_rate, pv_dividends
from moex_carry.config import load_settings
from moex_carry.costs.engine import CostProfile, costs_as_annual_rate
from moex_carry.data import MoexIssClient
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.data.dividends import apply_overrides, load_dividends
from moex_carry.domain.models import KeyRate
from moex_carry.pipeline import _fetch_candles, _future_price_scale, _parse_contract_specs
from moex_carry.strategy.orchestrator import generate_signal


def _load_key_rates() -> list[KeyRate]:
    path = Path("data/raw/key_rates.csv")
    if not path.exists():
        return []
    df = pd.read_csv(path)
    return [
        KeyRate(date=pd.to_datetime(row["date"]).date(), rate=float(row["rate"]))
        for _, row in df.iterrows()
    ]


def _find_first_entry(
    merged: pd.DataFrame,
    expiry: date,
    dividends,
    key_rates: list[KeyRate],
    cost_profile: CostProfile,
    settings,
) -> tuple[date | None, list[str], dict]:
    spread_series: list[float] = []
    for _, row in merged.iterrows():
        current_date: date = row["date"]
        spot = float(row["spot"])
        future = float(row["future"])
        days_to_expiry = (expiry - current_date).days
        time_years = max(days_to_expiry / 365.0, 0.0)

        key_rate = latest_rate(key_rates, current_date)
        key_rate_value = key_rate.rate if key_rate else 0.0
        pv_div = pv_dividends(dividends, current_date, expiry, key_rate_value)
        fair = fair_value(spot, pv_div, key_rate_value, time_years)
        spread_series.append(future - fair)

        implied = implied_rate(future, spot, pv_div, time_years)
        implied_net = implied - costs_as_annual_rate(cost_profile, time_years)
        required = key_rate_value + settings.strategy.term_premium_base + (
            settings.strategy.term_premium_slope * time_years
        )
        days_to_exdiv = min(
            [(event.ex_date - current_date).days for event in dividends if event.ex_date >= current_date]
            or [9999]
        )
        signal = generate_signal(
            spread_series=spread_series,
            implied_rate_net=implied_net,
            required_rate=required,
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
        if signal.action == "enter":
            return current_date, signal.reasons, signal.metrics
    return None, [], {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs-csv", type=str, default="data/output/top_pairs.csv")
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    parser.add_argument("--lookback-days", type=int, default=730)
    args = parser.parse_args()

    settings = load_settings(args.config)
    client = MoexIssClient(
        settings.moex.base_url,
        settings.moex.request_timeout_sec,
        max_retries=settings.moex.request_max_retries,
        retry_backoff_sec=settings.moex.request_retry_backoff_sec,
        retry_max_backoff_sec=settings.moex.request_retry_max_backoff_sec,
        fallback_ips=settings.moex.fallback_ips,
        force_fallback=settings.moex.force_fallback,
    )

    pairs = pd.read_csv(args.pairs_csv)
    if pairs.empty:
        raise SystemExit("Pairs list is empty.")

    futures_df = pd.read_csv("data/raw/futures.csv")
    specs = {spec.secid: spec for spec in _parse_contract_specs(futures_df)}
    key_rates = _load_key_rates()

    cost_profile = CostProfile(
        stock_commission_bps=settings.costs.stock_commission_bps,
        futures_commission_bps=settings.costs.futures_commission_bps,
        exchange_fee_bps=settings.costs.exchange_fee_bps,
        slippage_bps=settings.costs.slippage_bps,
    )

    today = date.today()
    lookback = today - timedelta(days=max(args.lookback_days, 1))

    total = 0
    entered = 0
    entered_at_start = 0
    entered_at_start_pairs = []

    for _, row in pairs.iterrows():
        stock = row["stock"]
        future = row["future"]
        spec = specs.get(future)
        if spec is None:
            continue

        total += 1
        expiry = spec.expiry
        future_scale = _future_price_scale(spec)

        stock_df = _fetch_candles(
            client,
            settings.moex.engine_shares,
            settings.moex.market_shares,
            settings.moex.shares_board,
            stock,
            lookback,
            today,
        )
        future_df = _fetch_candles(
            client,
            settings.moex.engine_futures,
            settings.moex.market_futures,
            settings.moex.futures_board,
            future,
            lookback,
            today,
            price_scale=future_scale,
        )
        merged = pd.merge(stock_df, future_df, on="date", how="inner")
        if merged.empty:
            continue
        merged = merged.rename(columns={stock: "spot", future: "future"})

        dividends = load_dividends(client, stock)
        dividends = apply_overrides(dividends, Path("data/dividends_overrides.csv"))

        first_date = merged["date"].iloc[0]
        entry_date, reasons, metrics = _find_first_entry(
            merged,
            expiry,
            dividends,
            key_rates,
            cost_profile,
            settings,
        )
        if entry_date is None:
            continue
        entered += 1
        if entry_date == first_date:
            entered_at_start += 1
            entered_at_start_pairs.append(
                f"{stock}/{future} ({entry_date}) reasons={','.join(reasons)} metrics={metrics}"
            )

    print(f"Pairs analyzed: {total}")
    print(f"Pairs with any entry: {entered}")
    print(f"Entries at start: {entered_at_start}")
    if entered:
        print(f"Share at start: {entered_at_start / entered:.2%}")
    if entered_at_start_pairs:
        print("Pairs entered at start:")
        for line in entered_at_start_pairs:
            print(" -", line)


if __name__ == "__main__":
    main()
