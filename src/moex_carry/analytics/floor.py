from __future__ import annotations

from dataclasses import dataclass

from moex_carry.analytics.funding import funding_cost


@dataclass
class FloorMetrics:
    floor_pnl: float
    floor_rate_annual: float
    floor_pass: bool
    capital_base: float
    costs_hold: float


def _capital_base_full_cash(spot_price: float) -> float:
    return float(spot_price)


def _capital_base_margin(
    spot_price: float,
    fut_price: float,
    margin_stock_pct: float,
    margin_fut_pct: float,
    var_margin_buffer_pct: float,
) -> float:
    margin_stock = float(spot_price) * float(margin_stock_pct)
    margin_fut = float(fut_price) * float(margin_fut_pct)
    var_buffer = float(spot_price) * float(var_margin_buffer_pct)
    return margin_stock + margin_fut + var_buffer


def compute_floor_metrics(
    spot_buy: float,
    fut_sell: float,
    div_sum: float,
    fees_rt: float,
    r_cb_annual: float,
    r_fund_annual: float,
    tau: float,
    dte: int,
    floor_tolerance: float = 0.0,
    riskbuffer_floor: float = 0.0,
    capital_base_mode: str = "FULL_CASH",
    margin_stock_pct: float = 0.0,
    margin_fut_pct: float = 0.0,
    var_margin_buffer_pct: float = 0.0,
) -> FloorMetrics:
    fund_cost = funding_cost(spot_buy, r_fund_annual, tau)
    costs_hold = float(fees_rt) + fund_cost + float(riskbuffer_floor)
    floor_pnl = (float(fut_sell) - float(spot_buy)) + float(div_sum) - costs_hold

    if capital_base_mode.upper() == "MARGIN_AWARE":
        capital_base = _capital_base_margin(
            spot_price=spot_buy,
            fut_price=fut_sell,
            margin_stock_pct=margin_stock_pct,
            margin_fut_pct=margin_fut_pct,
            var_margin_buffer_pct=var_margin_buffer_pct,
        )
    else:
        capital_base = _capital_base_full_cash(spot_buy)

    annualizer = 365.0 / float(dte) if dte > 0 else 0.0
    floor_rate_annual = (floor_pnl / capital_base) * annualizer if capital_base > 0 else 0.0
    floor_pass = floor_rate_annual >= float(r_cb_annual) - float(floor_tolerance)

    return FloorMetrics(
        floor_pnl=floor_pnl,
        floor_rate_annual=floor_rate_annual,
        floor_pass=floor_pass,
        capital_base=capital_base,
        costs_hold=costs_hold,
    )
