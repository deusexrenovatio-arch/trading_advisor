import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from moex_carry.analytics.carry import fair_value, implied_rate, pv_dividends
from moex_carry.config import load_settings
from moex_carry.costs.engine import CostProfile, costs_as_annual_rate
from moex_carry.costs.taxes import TaxProfile, apply_dividend_tax, apply_profit_tax
from moex_carry.data import MoexIssClient
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.data.dividends import apply_overrides, load_dividends
from moex_carry.domain.models import KeyRate
from moex_carry.pipeline import _fetch_candles, _future_price_scale, _parse_contract_specs
from moex_carry.backtest.report import compute_metrics
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


def _fetch_candles_interval(
    client: MoexIssClient,
    engine: str,
    market: str,
    board: str,
    secid: str,
    from_date: date,
    till_date: date,
    interval: int,
    price_scale: float,
) -> pd.DataFrame:
    raw = client.get_candles(engine, market, secid, board, from_date, till_date, interval=interval)
    df = pd.DataFrame(raw)
    if df.empty:
        return df
    if price_scale and price_scale != 1.0:
        df["close"] = pd.to_numeric(df["close"], errors="coerce") / price_scale
    df["timestamp"] = pd.to_datetime(df["begin"])
    df["date"] = df["timestamp"].dt.date
    df.rename(columns={"close": secid, "volume": f"{secid}_volume"}, inplace=True)
    return df[["timestamp", "date", secid, f"{secid}_volume"]]


def _bars_per_day(df: pd.DataFrame, date_col: str = "date") -> int:
    if date_col not in df.columns and "timestamp" in df.columns:
        df = df.copy()
        df["date"] = pd.to_datetime(df["timestamp"]).dt.date
        date_col = "date"
    if date_col not in df.columns:
        return 1
    counts = df.groupby(date_col).size()
    if counts.empty:
        return 1
    return max(int(round(counts.mean())), 1)


def _apply_slippage(direction: str, spot: float, future: float, slip_bps: float, side: str) -> tuple[float, float]:
    slip = slip_bps / 10000.0
    if side == "entry":
        if direction == "cash_and_carry":
            return spot * (1 + slip), future * (1 - slip)
        return spot * (1 - slip), future * (1 + slip)
    if direction == "cash_and_carry":
        return spot * (1 - slip), future * (1 + slip)
    return spot * (1 + slip), future * (1 - slip)


def _simulate(
    prices: pd.DataFrame,
    expiry: date,
    dividends,
    key_rates: list[KeyRate],
    costs: CostProfile,
    taxes: TaxProfile,
    settings,
    z_window: int,
    z_min_window: int,
    slippage_bps: float,
    time_col: str,
) -> dict:
    equity = 1.0
    equity_curve = []
    trades = 0
    spread_series: list[float] = []
    position = None
    entry_spot = 0.0
    entry_future = 0.0
    entry_date: date | None = None

    for _, row in prices.iterrows():
        current_ts = row[time_col]
        current_date = current_ts.date() if isinstance(current_ts, datetime) else current_ts
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
        implied_net = implied - costs_as_annual_rate(costs, time_years)
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
            z_window=z_window,
            z_min_window=z_min_window,
            z_entry=settings.strategy.z_entry,
            z_exit=settings.strategy.z_exit,
            implied_rate_buffer=settings.strategy.implied_rate_buffer,
            min_days_to_expiry=settings.strategy.min_days_to_expiry,
            min_days_to_exdiv=settings.strategy.min_days_to_exdiv,
        )

        if position is None and signal.action == "enter":
            position = signal.direction or "cash_and_carry"
            entry_spot, entry_future = _apply_slippage(position, spot, future, slippage_bps, "entry")
            entry_date = current_date
        elif position is not None and signal.action == "exit":
            exit_spot, exit_future = _apply_slippage(position, spot, future, slippage_bps, "exit")
            dividend_cash = sum(
                event.amount
                for event in dividends
                if entry_date and entry_date < event.ex_date <= current_date
            )
            dividend_cash = apply_dividend_tax(dividend_cash, taxes)
            cost_amount = costs_as_annual_rate(costs, time_years) * spot

            if position == "cash_and_carry":
                pnl = (exit_spot - entry_spot) - (exit_future - entry_future) + dividend_cash
            else:
                pnl = -(exit_spot - entry_spot) + (exit_future - entry_future) - dividend_cash
            pnl = apply_profit_tax(pnl - cost_amount, taxes)

            equity *= 1 + (pnl / max(entry_spot, 1e-6))
            trades += 1
            position = None
        equity_curve.append({"time": current_ts, "equity": equity})

    equity_series = pd.DataFrame(equity_curve).set_index("time")["equity"]
    metrics = compute_metrics(equity_series, []).__dict__
    return {
        "equity": equity_series,
        "metrics": metrics,
        "trades": trades,
        "start": equity_series.index.min(),
        "end": equity_series.index.max(),
        "points": len(equity_series),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock", type=str, required=True)
    parser.add_argument("--future", type=str, required=True)
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    parser.add_argument("--daily-lookback-days", type=int, default=730)
    parser.add_argument("--intraday-lookback-days", type=int, default=60)
    parser.add_argument("--interval-min", type=int, default=60)
    parser.add_argument("--start-date", type=str, default=None)
    parser.add_argument("--end-date", type=str, default=None)
    parser.add_argument("--slippage-bps", type=float, default=None)
    parser.add_argument("--no-scale-window", action="store_true")
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

    futures_df = pd.read_csv("data/raw/futures.csv")
    specs = {spec.secid: spec for spec in _parse_contract_specs(futures_df)}
    spec = specs.get(args.future)
    if spec is None:
        raise SystemExit(f"Future {args.future} not found in data/raw/futures.csv")
    expiry = spec.expiry
    future_scale = _future_price_scale(spec)

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
    slippage_bps = (
        float(args.slippage_bps) if args.slippage_bps is not None else settings.costs.slippage_bps
    )

    today = date.today()

    daily_from = today - timedelta(days=max(args.daily_lookback_days, 1))
    daily_stock = _fetch_candles(
        client,
        settings.moex.engine_shares,
        settings.moex.market_shares,
        settings.moex.shares_board,
        args.stock,
        daily_from,
        today,
    )
    daily_future = _fetch_candles(
        client,
        settings.moex.engine_futures,
        settings.moex.market_futures,
        settings.moex.futures_board,
        args.future,
        daily_from,
        today,
        price_scale=future_scale,
    )
    daily = pd.merge(daily_stock, daily_future, on="date", how="inner")
    if daily.empty:
        raise SystemExit("No daily overlap for выбранной пары.")
    daily = daily.rename(columns={args.stock: "spot", args.future: "future"})

    intraday_from = today - timedelta(days=max(args.intraday_lookback_days, 1))
    intra_stock = _fetch_candles_interval(
        client,
        settings.moex.engine_shares,
        settings.moex.market_shares,
        settings.moex.shares_board,
        args.stock,
        intraday_from,
        today,
        interval=args.interval_min,
        price_scale=1.0,
    )
    intra_future = _fetch_candles_interval(
        client,
        settings.moex.engine_futures,
        settings.moex.market_futures,
        settings.moex.futures_board,
        args.future,
        intraday_from,
        today,
        interval=args.interval_min,
        price_scale=future_scale,
    )
    intraday = pd.merge(intra_stock, intra_future, on="timestamp", how="inner")
    if intraday.empty:
        raise SystemExit("No intraday overlap for выбранной пары.")
    if "date" not in intraday.columns:
        if "date_x" in intraday.columns:
            intraday["date"] = intraday["date_x"]
        else:
            intraday["date"] = pd.to_datetime(intraday["timestamp"]).dt.date
    intraday = intraday.rename(columns={args.stock: "spot", args.future: "future"})

    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        return date.fromisoformat(value)

    start_date = _parse_date(args.start_date) or max(daily["date"].min(), intraday["date"].min())
    end_date = _parse_date(args.end_date) or min(daily["date"].max(), intraday["date"].max())
    if start_date > end_date:
        raise SystemExit("No overlapping period between daily and intraday data.")

    daily = daily[(daily["date"] >= start_date) & (daily["date"] <= end_date)]
    intraday = intraday[(intraday["date"] >= start_date) & (intraday["date"] <= end_date)]
    if daily.empty or intraday.empty:
        raise SystemExit("No data after aligning to the common period.")

    if args.no_scale_window:
        daily_window = settings.strategy.z_window
        daily_min_window = settings.strategy.z_min_window
        intra_window = settings.strategy.z_window
        intra_min_window = settings.strategy.z_min_window
    else:
        bars_per_day = _bars_per_day(intraday, date_col="date")
        daily_window = settings.strategy.z_window
        daily_min_window = settings.strategy.z_min_window
        intra_window = max(int(round(settings.strategy.z_window * bars_per_day)), 1)
        intra_min_window = max(int(round(settings.strategy.z_min_window * bars_per_day)), 1)

    daily_result = _simulate(
        daily[["date", "spot", "future"]],
        expiry,
        dividends,
        key_rates,
        cost_profile,
        tax_profile,
        settings,
        z_window=daily_window,
        z_min_window=daily_min_window,
        slippage_bps=slippage_bps,
        time_col="date",
    )
    intraday_result = _simulate(
        intraday[["timestamp", "date", "spot", "future"]],
        expiry,
        dividends,
        key_rates,
        cost_profile,
        tax_profile,
        settings,
        z_window=intra_window,
        z_min_window=intra_min_window,
        slippage_bps=slippage_bps,
        time_col="timestamp",
    )

    def _summ(label: str, result: dict) -> None:
        total_return = result["equity"].iloc[-1] - 1 if not result["equity"].empty else 0.0
        cagr = result["metrics"].get("cagr", 0.0)
        print(f"[{label}] period: {result['start']} -> {result['end']}")
        print(f"[{label}] bars: {result['points']}, trades: {result['trades']}")
        print(f"[{label}] total return: {total_return * 100:.2f}%")
        print(f"[{label}] CAGR: {cagr * 100:.2f}%")

    print(f"Pair: {args.stock}/{args.future}")
    print(f"Aligned period: {start_date} -> {end_date}")
    print(f"Slippage (bps): {slippage_bps}")
    print(f"Daily window: {daily_window} (min {daily_min_window})")
    print(f"Intraday window: {intra_window} (min {intra_min_window})")
    _summ("Daily", daily_result)
    _summ("Intraday", intraday_result)


if __name__ == "__main__":
    main()
