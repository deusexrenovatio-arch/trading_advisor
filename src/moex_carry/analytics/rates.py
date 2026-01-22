from __future__ import annotations


def term_premium(time_years: float, base: float, slope: float) -> float:
    if time_years <= 0:
        return 0.0
    return base + slope * time_years


def target_annual_rate(
    key_rate: float, risk_premium_base: float, term_premium_base: float, term_premium_slope: float, time_years: float
) -> float:
    return key_rate + risk_premium_base + term_premium(time_years, term_premium_base, term_premium_slope)
