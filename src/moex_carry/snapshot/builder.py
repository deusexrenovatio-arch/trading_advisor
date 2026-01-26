from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Iterable, Mapping, Optional

from moex_carry.analytics.dividends import div_sum, pv_dividends_exp
from moex_carry.analytics.floor import compute_floor_metrics
from moex_carry.analytics.liquidity import (
    avg_dollar_volume,
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
from moex_carry.analytics.time import days_to_expiry, year_fraction
from moex_carry.costs.engine import compute_rtc
from moex_carry.data.cbr_rates import latest_rate
from moex_carry.domain.models import DividendEvent, KeyRate
from moex_carry.domain.portfolio import (
    DailyInstrumentBar,
    PairSpec,
    SnapshotPerPair,
    SnapshotPerPairEvents,
    SnapshotPerPairLq,
)
from moex_carry.execution.model import build_execution_prices


def _as_of_datetime(as_of: date | datetime) -> datetime:
    if isinstance(as_of, datetime):
        if as_of.tzinfo is None:
            return as_of.replace(tzinfo=timezone.utc)
        return as_of
    return datetime.combine(as_of, time.min).replace(tzinfo=timezone.utc)


def _resolve_mid(bar: DailyInstrumentBar) -> Optional[float]:
    if bar.mid is not None:
        return float(bar.mid)
    if bar.bid is not None and bar.ask is not None:
        return (float(bar.bid) + float(bar.ask)) / 2.0
    for field in (bar.close, bar.last, bar.open, bar.vwap):
        if field is not None:
            return float(field)
    return None


def _index_bars(
    bars: Mapping[str, DailyInstrumentBar] | Iterable[DailyInstrumentBar] | None,
    as_of: date,
) -> dict[str, DailyInstrumentBar]:
    if bars is None:
        return {}
    if isinstance(bars, Mapping):
        indexed: dict[str, DailyInstrumentBar] = {}
        for secid, bar in bars.items():
            if isinstance(bar, DailyInstrumentBar) and bar.date == as_of:
                indexed[secid] = bar
        return indexed
    indexed = {}
    for bar in bars:
        if bar.date == as_of:
            indexed[bar.secid] = bar
    return indexed


def _group_dividends(dividends: Iterable[DividendEvent] | None) -> dict[str, list[DividendEvent]]:
    grouped: dict[str, list[DividendEvent]] = {}
    if dividends is None:
        return grouped
    for event in dividends:
        grouped.setdefault(event.secid, []).append(event)
    return grouped


def _resolve_rates(
    as_of: date,
    rates: Iterable[KeyRate] | None,
    rates_config: Mapping[str, Any],
) -> tuple[float, float, float]:
    key_rates = list(rates) if rates is not None else []
    key_rate_row = latest_rate(key_rates, as_of)
    base_rate = key_rate_row.rate if key_rate_row else 0.0
    r_cb = rates_config.get("r_cb_annual")
    r_fund = rates_config.get("r_fund_annual")
    r_disc = rates_config.get("r_disc_annual")
    r_cb_value = float(r_cb) if r_cb is not None else float(base_rate)
    r_fund_value = float(r_fund) if r_fund is not None else r_cb_value
    r_disc_value = float(r_disc) if r_disc is not None else r_cb_value
    return r_cb_value, r_fund_value, r_disc_value


def _resolve_price_mode(execution_config: Mapping[str, Any]) -> str:
    raw_mode = execution_config.get("price_mode") or execution_config.get("mode") or "BIDASK"
    mode = str(raw_mode).upper()
    if mode not in {"BIDASK", "OHLC", "AUTO"}:
        return "BIDASK"
    return mode


def _position_notional(
    spot_mid: Optional[float],
    multiplier: float,
    resolved_config: Mapping[str, Any],
) -> Optional[float]:
    portfolio = resolved_config.get("portfolio", {}) if isinstance(resolved_config, Mapping) else {}
    universe = resolved_config.get("universe", {}) if isinstance(resolved_config, Mapping) else {}

    if portfolio.get("capital_allocated_per_trade") is not None:
        return float(portfolio["capital_allocated_per_trade"])
    if portfolio.get("max_gross_notional") is not None:
        position_notional = float(portfolio["max_gross_notional"])
        max_pairs = universe.get("max_pairs")
        if max_pairs:
            position_notional = position_notional / max(int(max_pairs), 1)
        return position_notional
    if portfolio.get("account_equity") is not None:
        return float(portfolio["account_equity"])
    contracts = portfolio.get("max_contracts_per_pair")
    if spot_mid is not None and contracts is not None and multiplier:
        return float(spot_mid) * float(multiplier) * float(contracts)
    if spot_mid is not None and multiplier:
        return float(spot_mid) * float(multiplier)
    return None


def build_snapshot_universe(
    as_of: date,
    pairs: Iterable[PairSpec],
    stock_bars: Mapping[str, DailyInstrumentBar] | Iterable[DailyInstrumentBar] | None,
    fut_bars: Mapping[str, DailyInstrumentBar] | Iterable[DailyInstrumentBar] | None,
    dividends: Iterable[DividendEvent] | None,
    key_rates: Iterable[KeyRate] | None,
    resolved_config: Mapping[str, Any],
    *,
    events: Mapping[str, list[date]] | None = None,
) -> list[SnapshotPerPair]:
    stock_map = _index_bars(stock_bars, as_of)
    fut_map = _index_bars(fut_bars, as_of)
    dividend_map = _group_dividends(dividends)
    event_map = events or {}

    snapshots: list[SnapshotPerPair] = []
    execution_cfg = resolved_config.get("execution", {}) if isinstance(resolved_config, Mapping) else {}
    rates_cfg = resolved_config.get("rates", {}) if isinstance(resolved_config, Mapping) else {}
    costs_cfg = resolved_config.get("costs", {}) if isinstance(resolved_config, Mapping) else {}
    liquidity_cfg = resolved_config.get("liquidity", {}) if isinstance(resolved_config, Mapping) else {}
    strategy_cfg = resolved_config.get("strategy", {}) if isinstance(resolved_config, Mapping) else {}

    day_count = rates_cfg.get("day_count", "ACT/365")
    use_trading_days = bool(rates_cfg.get("use_trading_days", False))
    price_mode = _resolve_price_mode(execution_cfg)
    half_spread_bps = float(execution_cfg.get("half_spread_bps") or 0.0)

    for pair in pairs:
        warnings: list[str] = []
        stock_bar = stock_map.get(pair.stock_secid)
        fut_bar = fut_map.get(pair.future_secid)
        if stock_bar is None:
            warnings.append("missing_stock_bar")
        if fut_bar is None:
            warnings.append("missing_future_bar")

        spot_mid = _resolve_mid(stock_bar) if stock_bar else None
        fut_mid = _resolve_mid(fut_bar) if fut_bar else None
        spot_bid = float(stock_bar.bid) if stock_bar and stock_bar.bid is not None else None
        spot_ask = float(stock_bar.ask) if stock_bar and stock_bar.ask is not None else None
        fut_bid = float(fut_bar.bid) if fut_bar and fut_bar.bid is not None else None
        fut_ask = float(fut_bar.ask) if fut_bar and fut_bar.ask is not None else None

        if spot_bid is None or spot_ask is None:
            warnings.append("missing_stock_bid_ask")
        if fut_bid is None or fut_ask is None:
            warnings.append("missing_fut_bid_ask")

        expiry = pair.expiry
        dte = days_to_expiry(as_of, expiry, use_trading_days) if expiry else None
        tau = year_fraction(as_of, expiry, day_count) if expiry else None

        r_cb, r_fund, r_disc = _resolve_rates(as_of, key_rates, rates_cfg)
        dividends_for_stock = dividend_map.get(pair.stock_secid, [])
        pv_div = None
        div_sum_value = None
        if expiry:
            pv_div = pv_dividends_exp(dividends_for_stock, as_of, expiry, r_disc, day_count=day_count)
            div_sum_value = div_sum(dividends_for_stock, as_of, expiry)

        exec_prices = None
        if spot_mid is None or fut_mid is None:
            warnings.append("missing_mid_prices")
        else:
            effective_mode = price_mode
            if price_mode == "AUTO":
                if (spot_bid is None or spot_ask is None or fut_bid is None or fut_ask is None) and (
                    (stock_bar and (stock_bar.open is not None or stock_bar.close is not None))
                    or (fut_bar and (fut_bar.open is not None or fut_bar.close is not None))
                ):
                    effective_mode = "OHLC"
                else:
                    effective_mode = "BIDASK"
            if effective_mode == "OHLC":
                warnings.append("synthetic_bid_ask_ohlc")
            try:
                exec_prices = build_execution_prices(
                    stock_bid=spot_bid,
                    stock_ask=spot_ask,
                    fut_bid=fut_bid,
                    fut_ask=fut_ask,
                    stock_mid=spot_mid,
                    fut_mid=fut_mid,
                    stock_open=stock_bar.open if stock_bar else None,
                    stock_close=stock_bar.close if stock_bar else None,
                    fut_open=fut_bar.open if fut_bar else None,
                    fut_close=fut_bar.close if fut_bar else None,
                    mode=effective_mode,
                    half_spread_bps=half_spread_bps,
                    slip_stock_bps=float(execution_cfg.get("slip_stock_bps") or 0.0),
                    slip_fut_bps=float(execution_cfg.get("slip_fut_bps") or 0.0),
                    slip_fut_ticks=execution_cfg.get("slip_fut_ticks"),
                    tick_size_fut=execution_cfg.get("tick_size_fut") or pair.tick_size,
                )
            except ValueError as exc:
                warnings.append(f"execution_prices_error:{exc}")

        spread_mid_value = None
        spread_pct_value = None
        spread_entry_exec_value = None
        spread_exit_exec_value = None
        spread_entry_exec_pct = None
        spread_exit_exec_pct = None
        if spot_mid is not None and fut_mid is not None and pv_div is not None:
            spread_mid_value = spread_mid(spot_mid, pv_div, fut_mid)
            spread_pct_value = spread_pct(spread_mid_value, spot_mid)
        if exec_prices is not None and pv_div is not None and spot_mid is not None:
            spread_entry_exec_value = spread_entry_exec(exec_prices.stock_buy, pv_div, exec_prices.fut_sell)
            spread_exit_exec_value = spread_exit_exec(exec_prices.stock_sell, pv_div, exec_prices.fut_buy)
            spread_entry_exec_pct = spread_pct(spread_entry_exec_value, spot_mid)
            spread_exit_exec_pct = spread_pct(spread_exit_exec_value, spot_mid)

        rtc_pct = None
        rtc_metrics = None
        if exec_prices is not None and spot_mid is not None:
            multiplier = float(pair.multiplier) if pair.multiplier else 1.0
            rtc_metrics = compute_rtc(
                stock_buy=exec_prices.stock_buy,
                stock_sell=exec_prices.stock_sell,
                fut_buy=exec_prices.fut_buy,
                fut_sell=exec_prices.fut_sell,
                spot_mid=spot_mid,
                multiplier=multiplier,
                costs_config=costs_cfg,
            )
            rtc_pct = rtc_metrics.rtc_pct

        floor_rate_annual = None
        floor_pass = None
        if exec_prices is not None and div_sum_value is not None and tau is not None and dte is not None:
            floor_metrics = compute_floor_metrics(
                spot_buy=exec_prices.stock_buy,
                fut_sell=exec_prices.fut_sell,
                div_sum=div_sum_value,
                fees_rt=float(rtc_metrics.fees_rt) if rtc_metrics is not None else 0.0,
                r_cb_annual=r_cb,
                r_fund_annual=r_fund,
                tau=tau,
                dte=dte,
                floor_tolerance=float(strategy_cfg.get("floor_tolerance") or 0.0),
                riskbuffer_floor=float(strategy_cfg.get("riskbuffer_floor") or 0.0),
                capital_base_mode=str(strategy_cfg.get("capital_base_mode") or "FULL_CASH"),
                margin_stock_pct=float(strategy_cfg.get("margin_stock_pct") or 0.0),
                margin_fut_pct=float(strategy_cfg.get("margin_fut_pct") or 0.0),
                var_margin_buffer_pct=float(strategy_cfg.get("var_margin_buffer_pct") or 0.0),
            )
            floor_rate_annual = floor_metrics.floor_rate_annual
            floor_pass = floor_metrics.floor_pass

        spread_bps_stock = spread_bps(spot_bid, spot_ask, spot_mid)
        spread_bps_fut = spread_bps(fut_bid, fut_ask, fut_mid)
        multiplier = float(pair.multiplier) if pair.multiplier else 1.0
        dollar_vol_stock = dollar_volume(spot_mid, stock_bar.volume if stock_bar else None)
        dollar_vol_fut = dollar_volume(fut_mid, fut_bar.volume if fut_bar else None, multiplier=multiplier)
        avg_dollar = avg_dollar_volume(dollar_vol_stock, dollar_vol_fut)
        position_notional = _position_notional(spot_mid, multiplier, resolved_config)
        days_exit = days_to_exit(position_notional, avg_dollar, liquidity_cfg.get("participation_rate"))
        liquidity_pass = evaluate_liquidity(
            spread_bps_stock_value=spread_bps_stock,
            spread_bps_fut_value=spread_bps_fut,
            dollar_vol_stock_value=dollar_vol_stock,
            dollar_vol_fut_value=dollar_vol_fut,
            open_interest=fut_bar.open_interest if fut_bar else None,
            days_to_exit_value=days_exit,
            max_spread_bps_stock=liquidity_cfg.get("max_spread_bps_stock"),
            max_spread_bps_fut=liquidity_cfg.get("max_spread_bps_fut"),
            min_dollar_vol_stock=liquidity_cfg.get("min_avg_dollarvol_stock"),
            min_dollar_vol_fut=liquidity_cfg.get("min_avg_dollarvol_fut"),
            min_open_interest=liquidity_cfg.get("min_open_interest"),
            max_days_to_exit=liquidity_cfg.get("max_days_to_exit"),
        )

        dividend_ex_dates = [
            event.ex_date for event in dividends_for_stock if expiry and as_of < event.ex_date <= expiry
        ]
        if pair.stock_secid in event_map:
            dividend_ex_dates = list(dict.fromkeys(dividend_ex_dates + event_map[pair.stock_secid]))

        snapshot = SnapshotPerPair(
            as_of=_as_of_datetime(as_of),
            stock_secid=pair.stock_secid,
            future_secid=pair.future_secid,
            expiry=expiry,
            spot_bid=spot_bid,
            spot_ask=spot_ask,
            spot_mid=spot_mid,
            spot_open=float(stock_bar.open) if stock_bar and stock_bar.open is not None else None,
            spot_close=float(stock_bar.close) if stock_bar and stock_bar.close is not None else None,
            future_bid=fut_bid,
            future_ask=fut_ask,
            future_mid=fut_mid,
            future_open=float(fut_bar.open) if fut_bar and fut_bar.open is not None else None,
            future_close=float(fut_bar.close) if fut_bar and fut_bar.close is not None else None,
            dte=dte,
            tau=tau,
            pv_div=pv_div,
            div_sum=div_sum_value,
            spread_mid=spread_mid_value,
            spread_pct=spread_pct_value,
            spread_entry_exec=spread_entry_exec_value,
            spread_exit_exec=spread_exit_exec_value,
            spread_entry_exec_pct=spread_entry_exec_pct,
            spread_exit_exec_pct=spread_exit_exec_pct,
            rtc_pct=rtc_pct,
            floor_rate_annual=floor_rate_annual,
            floor_pass=floor_pass,
            lq=SnapshotPerPairLq(
                spread_bps_stock=spread_bps_stock,
                spread_bps_fut=spread_bps_fut,
                dollar_vol_stock=dollar_vol_stock,
                dollar_vol_fut=dollar_vol_fut,
                avg_dollar_vol=avg_dollar,
                days_to_exit=days_exit,
                open_interest=fut_bar.open_interest if fut_bar else None,
                liquidity_pass=liquidity_pass,
            ),
            events=SnapshotPerPairEvents(
                dividend_ex_dates=dividend_ex_dates,
                warnings=warnings,
            ),
        )
        snapshots.append(snapshot)
    return snapshots
