from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

import pandas as pd

from moex_carry.analytics.alpha import round_trip_cost
from moex_carry.analytics.dividends import div_sum, pv_dividends_exp
from moex_carry.analytics.floor import compute_floor_metrics
from moex_carry.analytics.spread import spread_entry_exec, spread_exit_exec, spread_pct
from moex_carry.analytics.time import days_to_expiry, year_fraction
from moex_carry.costs.engine import CostProfile, fut_fee_per_share, round_trip_fees, stock_fee_per_share
from moex_carry.costs.taxes import TaxProfile, apply_dividend_tax, apply_profit_tax
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.domain.models import DividendEvent, KeyRate, Trade
from moex_carry.backtest.report import compute_metrics
from moex_carry.execution.model import build_execution_prices
from moex_carry.strategy.spread_carry_alpha import SpreadCarryState, step_spread_carry_alpha


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.Series
    metrics: dict[str, float]


def backtest_pair(
    prices: pd.DataFrame,
    expiry: date,
    dividends: Iterable[DividendEvent],
    key_rates: Iterable[KeyRate],
    costs: CostProfile,
    taxes: TaxProfile,
    strategy_config,
    multiplier: float = 1.0,
    tick_size_fut: Optional[float] = None,
) -> BacktestResult:
    dividends = list(dividends)
    key_rates = list(key_rates)
    trades: list[Trade] = []
    position: Optional[Trade] = None
    entry_spot = 0.0
    entry_future = 0.0
    entry_date: Optional[date] = None
    equity = 1.0
    equity_curve = []
    alpha_exit_count = 0
    hold_days: list[int] = []
    state = SpreadCarryState()

    for _, row in prices.iterrows():
        spot = float(row["spot"])
        future = float(row["future"])
        current_date: date = row["date"]
        dte = days_to_expiry(current_date, expiry, strategy_config.use_trading_days)
        tau_exp = year_fraction(current_date, expiry, strategy_config.day_count)

        key_rate = latest_rate(key_rates, current_date)
        key_rate_value = key_rate.rate if key_rate else 0.0
        r_cb = strategy_config.r_cb_annual if strategy_config.r_cb_annual is not None else key_rate_value
        r_fund = strategy_config.r_fund_annual if strategy_config.r_fund_annual is not None else r_cb
        r_disc = strategy_config.r_disc_annual if strategy_config.r_disc_annual is not None else r_cb

        pv_div = pv_dividends_exp(dividends, current_date, expiry, r_disc, day_count=strategy_config.day_count)
        div_sum_value = div_sum(dividends, current_date, expiry)

        resolved_tick_size = (
            strategy_config.tick_size_fut
            if strategy_config.tick_size_fut is not None
            else tick_size_fut
        )
        exec_prices = build_execution_prices(
            stock_bid=None,
            stock_ask=None,
            fut_bid=None,
            fut_ask=None,
            stock_mid=spot,
            fut_mid=future,
            slip_stock_bps=strategy_config.slip_stock_bps,
            slip_fut_bps=strategy_config.slip_fut_bps,
            slip_fut_ticks=strategy_config.slip_fut_ticks,
            tick_size_fut=resolved_tick_size or 0.0,
        )
        fee_stock_bps = (
            strategy_config.fee_stock_bps
            if strategy_config.fee_stock_bps is not None
            else costs.stock_commission_bps
        )
        stock_fee = stock_fee_per_share(
            spot,
            fee_per_share=strategy_config.fee_stock_per_share,
            fee_bps=fee_stock_bps,
        )
        fut_fee_per_contract = strategy_config.fee_fut_per_contract or 0.0
        fut_fee = fut_fee_per_share(fut_fee_per_contract, multiplier)
        fees_rt = round_trip_fees(stock_fee, fut_fee)
        rtc = round_trip_cost(
            exec_prices.stock_buy,
            exec_prices.stock_sell,
            exec_prices.fut_buy,
            exec_prices.fut_sell,
            fees_rt,
        )
        rtc_pct = rtc / spot if spot else 0.0
        tp_net = strategy_config.TP_pct + rtc_pct
        sl_net = strategy_config.SL_pct + rtc_pct

        floor_metrics = compute_floor_metrics(
            spot_buy=exec_prices.stock_buy,
            fut_sell=exec_prices.fut_sell,
            div_sum=div_sum_value,
            fees_rt=fees_rt,
            r_cb_annual=r_cb,
            r_fund_annual=r_fund,
            tau=tau_exp,
            dte=dte,
            floor_tolerance=strategy_config.floor_tolerance,
            riskbuffer_floor=strategy_config.riskbuffer_floor,
            capital_base_mode=strategy_config.capital_base_mode,
            margin_stock_pct=strategy_config.margin_stock_pct,
            margin_fut_pct=strategy_config.margin_fut_pct,
            var_margin_buffer_pct=strategy_config.var_margin_buffer_pct,
        )

        spread_entry_exec_value = spread_entry_exec(exec_prices.stock_buy, pv_div, exec_prices.fut_sell)
        spread_exit_exec_value = spread_exit_exec(exec_prices.stock_sell, pv_div, exec_prices.fut_buy)
        spread_pct_entry_exec = spread_pct(spread_entry_exec_value, spot)
        spread_pct_exit_exec = spread_pct(spread_exit_exec_value, spot)

        signal = step_spread_carry_alpha(
            state,
            as_of=current_date,
            floor_pass=floor_metrics.floor_pass,
            liquidity_pass=True,
            spread_pct_entry_exec=spread_pct_entry_exec,
            spread_pct_exit_exec=spread_pct_exit_exec,
            tp_net=tp_net,
            sl_net=sl_net,
            dte=dte,
            min_dte_entry=strategy_config.min_DTE_entry,
            close_buffer_days=strategy_config.close_buffer_days,
            h_max_days=strategy_config.H_max_days,
            entry_filter_ok=True,
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
            entry_spot = exec_prices.stock_buy
            entry_future = exec_prices.fut_sell
            entry_date = current_date
        elif position is not None and signal.action == "exit":
            dividend_cash = sum(
                event.amount
                for event in dividends
                if position.entry_date < event.ex_date <= current_date
            )
            dividend_cash = apply_dividend_tax(dividend_cash, taxes)
            hold_tau = year_fraction(entry_date or current_date, current_date, strategy_config.day_count)
            funding_cost = entry_spot * r_fund * hold_tau
            pnl = (exec_prices.stock_sell - entry_spot) - (exec_prices.fut_buy - entry_future)
            pnl += dividend_cash - funding_cost - fees_rt
            pnl = apply_profit_tax(pnl, taxes)
            position.exit_date = current_date
            position.exit_price = future
            position.pnl = pnl
            trades.append(position)
            equity *= 1 + (pnl / max(entry_spot, 1e-6))
            if "tp" in signal.reasons:
                alpha_exit_count += 1
            if entry_date is not None:
                hold_days.append((current_date - entry_date).days)
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
        key_rate = latest_rate(key_rates, current_date)
        key_rate_value = key_rate.rate if key_rate else 0.0
        r_cb = strategy_config.r_cb_annual if strategy_config.r_cb_annual is not None else key_rate_value
        r_fund = strategy_config.r_fund_annual if strategy_config.r_fund_annual is not None else r_cb
        hold_tau = year_fraction(position.entry_date, current_date, strategy_config.day_count)
        funding_cost = entry_spot * r_fund * hold_tau
        fee_stock_bps = (
            strategy_config.fee_stock_bps
            if strategy_config.fee_stock_bps is not None
            else costs.stock_commission_bps
        )
        stock_fee = stock_fee_per_share(
            spot,
            fee_per_share=strategy_config.fee_stock_per_share,
            fee_bps=fee_stock_bps,
        )
        fut_fee_per_contract = strategy_config.fee_fut_per_contract or 0.0
        fut_fee = fut_fee_per_share(fut_fee_per_contract, multiplier)
        fees_rt = round_trip_fees(stock_fee, fut_fee)
        pnl = (spot - entry_spot) - (future - entry_future) + dividend_cash - funding_cost - fees_rt
        pnl = apply_profit_tax(pnl, taxes)
        position.exit_date = current_date
        position.exit_price = future
        position.pnl = pnl
        trades.append(position)
        equity *= 1 + (pnl / max(entry_spot, 1e-6))
        hold_days.append((current_date - position.entry_date).days)
        position = None

    equity_series = pd.DataFrame(equity_curve).set_index("date")["equity"]
    trade_returns = [trade.pnl / max(trade.entry_price, 1e-6) for trade in trades if trade.pnl]
    metrics = compute_metrics(equity_series, trade_returns).__dict__
    total_trades = len(trades)
    metrics["share_alpha_exits"] = (alpha_exit_count / total_trades) if total_trades else 0.0
    metrics["avg_hold_days"] = float(sum(hold_days) / len(hold_days)) if hold_days else 0.0
    return BacktestResult(trades=trades, equity_curve=equity_series, metrics=metrics)
