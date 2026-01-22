from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

import pandas as pd

from moex_carry.analytics.carry import fair_value, implied_rate, pv_dividends
from moex_carry.analytics.rates import target_annual_rate
from moex_carry.costs.engine import CostProfile, costs_as_annual_rate
from moex_carry.costs.taxes import TaxProfile, apply_dividend_tax, apply_profit_tax
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.domain.models import DividendEvent, KeyRate, Trade
from moex_carry.backtest.report import compute_metrics
from moex_carry.strategy.orchestrator import generate_signal


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.Series
    metrics: dict[str, float]


def _trade_pnl(
    direction: str,
    spot_entry: float,
    future_entry: float,
    spot_exit: float,
    future_exit: float,
    dividends: float,
    costs: float,
) -> float:
    if direction == "cash_and_carry":
        pnl = (spot_exit - spot_entry) - (future_exit - future_entry) + dividends
    else:
        pnl = -(spot_exit - spot_entry) + (future_exit - future_entry) - dividends
    return pnl - costs


def backtest_pair(
    prices: pd.DataFrame,
    expiry: date,
    dividends: Iterable[DividendEvent],
    key_rates: Iterable[KeyRate],
    costs: CostProfile,
    taxes: TaxProfile,
    strategy_config,
) -> BacktestResult:
    dividends = list(dividends)
    key_rates = list(key_rates)
    trades: list[Trade] = []
    position: Optional[Trade] = None
    entry_spot = 0.0
    entry_future = 0.0
    equity = 1.0
    equity_curve = []

    spread_series: list[float] = []

    for _, row in prices.iterrows():
        spot = float(row["spot"])
        future = float(row["future"])
        current_date: date = row["date"]
        days_to_expiry = (expiry - current_date).days
        time_years = max(days_to_expiry / 365.0, 0.0)

        key_rate = latest_rate(key_rates, current_date)
        key_rate_value = key_rate.rate if key_rate else 0.0

        pv_div = pv_dividends(dividends, current_date, expiry, key_rate_value)
        fair = fair_value(spot, pv_div, key_rate_value, time_years)
        spread_series.append(future - fair)

        implied = implied_rate(future, spot, pv_div, time_years)
        implied_net = implied - costs_as_annual_rate(costs, time_years)
        required = target_annual_rate(
            key_rate_value,
            risk_premium_base=0.0,
            term_premium_base=strategy_config.term_premium_base,
            term_premium_slope=strategy_config.term_premium_slope,
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
            z_window=strategy_config.z_window,
            z_min_window=strategy_config.z_min_window,
            z_entry=strategy_config.z_entry,
            z_exit=strategy_config.z_exit,
            implied_rate_buffer=strategy_config.implied_rate_buffer,
            min_days_to_expiry=strategy_config.min_days_to_expiry,
            min_days_to_exdiv=strategy_config.min_days_to_exdiv,
        )

        if position is None and signal.action == "enter":
            position = Trade(
                entry_date=current_date,
                exit_date=None,
                stock_secid=row.get("stock_secid", ""),
                future_secid=row.get("future_secid", ""),
                direction=signal.direction or "cash_and_carry",
                entry_price=future,
                exit_price=None,
                pnl=None,
            )
            entry_spot = spot
            entry_future = future
        elif position is not None and signal.action == "exit":
            dividend_cash = sum(
                event.amount
                for event in dividends
                if position.entry_date < event.ex_date <= current_date
            )
            dividend_cash = apply_dividend_tax(dividend_cash, taxes)
            cost_amount = costs_as_annual_rate(costs, time_years) * spot
            pnl = _trade_pnl(
                position.direction,
                entry_spot,
                entry_future,
                spot,
                future,
                dividend_cash,
                cost_amount,
            )
            pnl = apply_profit_tax(pnl, taxes)
            position.exit_date = current_date
            position.exit_price = future
            position.pnl = pnl
            trades.append(position)
            equity *= 1 + (pnl / max(entry_spot, 1e-6))
            position = None
        equity_curve.append({"date": current_date, "equity": equity})

    if position is not None:
        last_row = prices.iloc[-1]
        spot = float(last_row["spot"])
        future = float(last_row["future"])
        current_date = last_row["date"]
        dividend_cash = sum(
            event.amount for event in dividends if position.entry_date < event.ex_date <= current_date
        )
        dividend_cash = apply_dividend_tax(dividend_cash, taxes)
        cost_amount = costs_as_annual_rate(costs, 1 / 365.0) * spot
        pnl = _trade_pnl(
            position.direction, entry_spot, entry_future, spot, future, dividend_cash, cost_amount
        )
        pnl = apply_profit_tax(pnl, taxes)
        position.exit_date = current_date
        position.exit_price = future
        position.pnl = pnl
        trades.append(position)
        equity *= 1 + (pnl / max(entry_spot, 1e-6))
        position = None

    equity_series = pd.DataFrame(equity_curve).set_index("date")["equity"]
    trade_returns = [trade.pnl / max(trade.entry_price, 1e-6) for trade in trades if trade.pnl]
    metrics = compute_metrics(equity_series, trade_returns).__dict__
    return BacktestResult(trades=trades, equity_curve=equity_series, metrics=metrics)
