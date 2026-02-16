import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from moex_carry.analytics.carry import fair_value, implied_rate, pv_dividends
from moex_carry.config import load_settings
from moex_carry.costs.engine import CostProfile, costs_as_annual_rate
from moex_carry.costs.taxes import TaxProfile
from moex_carry.data import MoexIssClient
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.data.dividends import apply_overrides, load_dividends
from moex_carry.domain.models import KeyRate
from moex_carry.pipeline import _fetch_candles, _future_price_scale, _parse_contract_specs
from moex_carry.strategy.orchestrator import generate_signal
from moex_carry.backtest.engine import backtest_pair


def _load_key_rates() -> list[KeyRate]:
    path = Path("data/raw/key_rates.csv")
    if not path.exists():
        return []
    df = pd.read_csv(path)
    return [
        KeyRate(date=pd.to_datetime(row["date"]).date(), rate=float(row["rate"]))
        for _, row in df.iterrows()
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock", type=str, required=True)
    parser.add_argument("--future", type=str, required=True)
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

    today = date.today()
    lookback = today - timedelta(days=max(args.lookback_days, 1))

    futures_df = pd.read_csv("data/raw/futures.csv")
    specs = {spec.secid: spec for spec in _parse_contract_specs(futures_df)}
    spec = specs.get(args.future)
    if spec is None:
        raise SystemExit(f"Future {args.future} not found in data/raw/futures.csv")
    expiry = spec.expiry
    future_scale = _future_price_scale(spec)

    stock_df = _fetch_candles(
        client,
        settings.moex.engine_shares,
        settings.moex.market_shares,
        settings.moex.shares_board,
        args.stock,
        lookback,
        today,
    )
    future_df = _fetch_candles(
        client,
        settings.moex.engine_futures,
        settings.moex.market_futures,
        settings.moex.futures_board,
        args.future,
        lookback,
        today,
        price_scale=future_scale,
    )
    merged = pd.merge(stock_df, future_df, on="date", how="inner")
    if merged.empty:
        raise SystemExit("No overlapping candles for выбранной пары.")

    merged = merged.rename(columns={args.stock: "spot", args.future: "future"})
    key_rates = _load_key_rates()
    dividends = load_dividends(client, args.stock)
    dividends = apply_overrides(dividends, Path("data/dividends_overrides.csv"))

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

    total_return = result.equity_curve.iloc[-1] - 1 if not result.equity_curve.empty else 0.0
    cagr = result.metrics.get("cagr", 0.0)

    first_date = merged["date"].iloc[0]
    last_date = merged["date"].iloc[-1]

    spread_series: list[float] = []
    position: str | None = None
    first_entry = None

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

        if position is None and signal.action == "enter":
            position = signal.direction or "cash_and_carry"
            first_entry = {
                "date": current_date,
                "direction": position,
                "reasons": signal.reasons,
                "metrics": signal.metrics,
                "implied_rate_net": implied_net,
                "required_rate": required,
            }
            break

    print(f"Pair: {args.stock}/{args.future}")
    print(f"Period: {first_date} -> {last_date} ({len(merged)} points)")
    print(f"Total return: {total_return * 100:.2f}%")
    print(f"CAGR: {cagr * 100:.2f}%")
    if first_entry:
        print(
            "First entry:",
            first_entry["date"],
            "| direction:",
            first_entry["direction"],
            "| reasons:",
            ",".join(first_entry["reasons"]),
        )
        print(
            f"implied_rate_net={first_entry['implied_rate_net']:.4f} "
            f"required_rate={first_entry['required_rate']:.4f}"
        )
        print(f"metrics={first_entry['metrics']}")
        print(f"entered_at_start={first_entry['date'] == first_date}")
    else:
        print("First entry: none")


if __name__ == "__main__":
    main()
