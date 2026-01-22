---
name: risk-profile-gates
description: Deterministic risk profile gates for intraday futures decisions.
---

# Risk Profile Gates

## Purpose
Define a fixed set of risk limits that must be satisfied before any decision is
approved. The output is a deterministic pass/fail report with explicit reasons.

## Required inputs
- account_equity
- account_currency
- max_risk_per_trade_pct
- max_daily_loss_pct
- max_open_risk_pct
- max_leverage
- max_margin_pct
- max_contracts_per_instrument
- max_positions
- max_correlated_exposure_pct
- stop_loss_required
- time_stop_minutes
- slippage_tolerance_ticks

## Deterministic checks
- All percentage limits are within 0.1 to 10.0 inclusive.
- max_open_risk_pct >= max_risk_per_trade_pct.
- max_daily_loss_pct >= 2 * max_risk_per_trade_pct.
- max_leverage >= 1 and <= 10.
- max_margin_pct between 10 and 100.
- max_contracts_per_instrument is a positive integer.
- max_positions is a positive integer.
- stop_loss_required must be true.
- time_stop_minutes between 1 and 240.
- slippage_tolerance_ticks between 0 and 10.

## Output JSON template
```
{
  "risk_profile": {
    "account_equity": 100000,
    "account_currency": "RUB",
    "max_risk_per_trade_pct": 0.5,
    "max_daily_loss_pct": 2.0,
    "max_open_risk_pct": 1.5,
    "max_leverage": 5,
    "max_margin_pct": 60,
    "max_contracts_per_instrument": 20,
    "max_positions": 6,
    "max_correlated_exposure_pct": 40,
    "stop_loss_required": true,
    "time_stop_minutes": 90,
    "slippage_tolerance_ticks": 2
  },
  "risk_gate_result": {
    "passed": true,
    "checks": [
      {
        "id": "risk_limits_range",
        "passed": true,
        "message": "All limits within allowed ranges."
      }
    ],
    "actions": []
  }
}
```
