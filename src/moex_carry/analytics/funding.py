from __future__ import annotations


def funding_cost(spot_price: float, r_fund_annual: float, tau: float) -> float:
    if spot_price is None or r_fund_annual is None or tau is None:
        return 0.0
    return float(spot_price) * float(r_fund_annual) * float(max(tau, 0.0))
