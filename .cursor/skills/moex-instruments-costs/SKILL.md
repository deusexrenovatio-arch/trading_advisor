---
name: moex-instruments-costs
description: Cost model template and checks for MOEX futures instruments.
---

# MOEX Instruments Cost Model

## Purpose
Provide a deterministic cost model used by strategy evaluation, risk checks,
and decision logs.

## Required inputs
- instrument_code
- tick_size
- tick_value
- commission_per_side
- exchange_fee_per_side
- clearing_fee_per_side
- regulatory_fee_per_side
- slippage_ticks
- spread_ticks
- tax_rate

## Deterministic checks
- tick_size > 0 and tick_value > 0.
- All fee components are >= 0.
- slippage_ticks and spread_ticks are >= 0.
- tax_rate between 0 and 1.

## Output JSON template
```
{
  "instrument_cost_model": {
    "instrument_code": "RIH5",
    "tick_size": 0.01,
    "tick_value": 10,
    "commission_per_side": 1.5,
    "exchange_fee_per_side": 0.2,
    "clearing_fee_per_side": 0.1,
    "regulatory_fee_per_side": 0.0,
    "slippage_ticks": 1,
    "spread_ticks": 1,
    "tax_rate": 0.13
  },
  "computed": {
    "fee_side": 1.8,
    "round_trip_fee": 3.6,
    "slippage_cost": 30,
    "round_trip_cost": 33.6,
    "break_even_ticks": 3.36,
    "break_even_points": 0.0336
  }
}
```

## Formula reference
- fee_side = commission + exchange + clearing + regulatory
- round_trip_fee = fee_side * 2
- slippage_cost = (slippage_ticks * 2 + spread_ticks) * tick_value
- round_trip_cost = round_trip_fee + slippage_cost
- break_even_ticks = round_trip_cost / tick_value
- break_even_points = break_even_ticks * tick_size
