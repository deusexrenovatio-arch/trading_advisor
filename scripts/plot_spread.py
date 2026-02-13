import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from moex_carry.analytics.carry import fair_value, implied_rate, pv_dividends
from moex_carry.analytics.rates import target_annual_rate
from moex_carry.analytics.stats import spread_stats
from moex_carry.config import load_settings
from moex_carry.data import CbrKeyRateClient, MoexIssClient
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.data.dividends import apply_overrides, load_dividends
from moex_carry.pipeline import _fetch_candles, _future_price_scale, _parse_contract_specs
from moex_carry.strategy.orchestrator import generate_signal


def _load_key_rates(settings, config_path: str | None) -> list:
    key_rates_path = Path("data/raw/key_rates.csv")
    if key_rates_path.exists():
        df = pd.read_csv(key_rates_path)
        return [
            (pd.to_datetime(row["date"]).date(), float(row["rate"]))
            for _, row in df.iterrows()
        ]
    client = CbrKeyRateClient(settings.cbr.base_url, settings.cbr.key_rate_path, settings.moex.request_timeout_sec)
    rates = client.get_key_rate_history()
    return [(rate.date, rate.rate) for rate in rates]


def _latest_rate(key_rates: list[tuple[date, float]], as_of: date) -> float:
    eligible = [rate for rate in key_rates if rate[0] <= as_of]
    if not eligible:
        return 0.0
    eligible.sort(key=lambda item: item[0])
    return eligible[-1][1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock", type=str, required=True)
    parser.add_argument("--future", type=str, required=True)
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    parser.add_argument("--lookback-days", type=int, default=730)
    parser.add_argument("--output", type=str, default=None)
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

    key_rates = _load_key_rates(settings, args.config)
    dividends = load_dividends(client, args.stock)
    dividends = apply_overrides(dividends, Path("data/dividends_overrides.csv"))

    spread_series: list[float] = []
    trend_series: list[float] = []
    z_series: list[float] = []
    dates: list[date] = []
    entries: list[tuple[date, float, str]] = []
    exits: list[tuple[date, float]] = []

    position: str | None = None

    for _, row in merged.iterrows():
        current_date: date = row["date"]
        spot = float(row[args.stock])
        future = float(row[args.future])
        days_to_expiry = (expiry - current_date).days
        time_years = max(days_to_expiry / 365.0, 0.0)

        key_rate_value = _latest_rate(key_rates, current_date)
        pv_div = pv_dividends(dividends, current_date, expiry, key_rate_value)
        fair = fair_value(spot, pv_div, key_rate_value, time_years)
        spread = future - fair
        spread_series.append(spread)

        stats = spread_stats(
            spread_series,
            window=settings.strategy.z_window,
            min_window=settings.strategy.z_min_window,
        )
        trend_series.append(stats["trend"])
        z_series.append(stats["trend_zscore"])
        dates.append(current_date)

        implied = implied_rate(future, spot, pv_div, time_years)
        implied_net = implied
        required = target_annual_rate(
            key_rate_value,
            risk_premium_base=0.0,
            term_premium_base=settings.strategy.term_premium_base,
            term_premium_slope=settings.strategy.term_premium_slope,
            time_years=time_years,
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
            entries.append((current_date, spread, position))
        elif position is not None and signal.action == "exit":
            exits.append((current_date, spread))
            position = None

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
    )
    fig.add_trace(go.Scatter(x=dates, y=spread_series, name="Spread (F - Fair)"), row=1, col=1)
    fig.add_trace(go.Scatter(x=dates, y=trend_series, name="Trend (rolling)"), row=1, col=1)

    if entries:
        entry_x = [item[0] for item in entries]
        entry_y = [item[1] for item in entries]
        entry_dir = [item[2] for item in entries]
        colors = ["green" if d == "cash_and_carry" else "red" for d in entry_dir]
        fig.add_trace(
            go.Scatter(
                x=entry_x,
                y=entry_y,
                mode="markers",
                marker={"symbol": "triangle-up", "size": 10, "color": colors},
                name="Entry",
            ),
            row=1,
            col=1,
        )
    if exits:
        exit_x = [item[0] for item in exits]
        exit_y = [item[1] for item in exits]
        fig.add_trace(
            go.Scatter(
                x=exit_x,
                y=exit_y,
                mode="markers",
                marker={"symbol": "x", "size": 9, "color": "black"},
                name="Exit",
            ),
            row=1,
            col=1,
        )

    fig.add_trace(go.Scatter(x=dates, y=z_series, name="Trend z-score"), row=2, col=1)
    fig.add_hline(y=settings.strategy.z_entry, row=2, col=1, line_dash="dash")
    fig.add_hline(y=-settings.strategy.z_entry, row=2, col=1, line_dash="dash")
    fig.add_hline(y=0, row=2, col=1, line_dash="dot")

    fig.update_layout(
        title=f"{args.stock}/{args.future} spread with entry/exit signals",
        height=800,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )

    output_path = args.output
    if output_path is None:
        output_dir = Path("data/output/plots")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / f"{args.stock}_{args.future}_spread.html")

    fig.write_html(output_path)
    print(f"Saved plot to {output_path}")
    print(f"Entries: {len(entries)}, exits: {len(exits)}")


if __name__ == "__main__":
    main()
