---
name: moex-instruments-costs
description: Deterministic cost model template and break-even checks for MOEX futures instruments. Use when cost/tax assumptions are added or changed, and during strategy rechecks before push. Co-use with intraday-futures-trading-advisor, risk-profile-gates, and spread-arbitrage.
---

# MOEX Instruments Cost Model

## Purpose
Provide a deterministic cost model used by strategy evaluation, risk checks, and decision logs.

## Skill dependencies and lifecycle gates
- Strategy planning phase: use with `intraday-futures-trading-advisor`.
- Risk validation phase: pair with `risk-profile-gates`.
- Spread strategy phase: add `spread-arbitrage` for two-leg checks.
- Recheck/pre-push phase: rerun cost calculations when any fee/slippage/tax parameter changes.

## Required inputs
- `instrument_code`
- `tick_size`
- `tick_value`
- `commission_per_side`
- `exchange_fee_per_side`
- `clearing_fee_per_side`
- `regulatory_fee_per_side`
- `slippage_ticks`
- `spread_ticks`
- `tax_rate`

## Deterministic checks
- `tick_size > 0` and `tick_value > 0`.
- All fee components are `>= 0`.
- `slippage_ticks >= 0` and `spread_ticks >= 0`.
- `tax_rate` is within `[0, 1]`.

## Output JSON template
```json
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
- `fee_side = commission + exchange + clearing + regulatory`
- `round_trip_fee = fee_side * 2`
- `slippage_cost = (slippage_ticks * 2 + spread_ticks) * tick_value`
- `round_trip_cost = round_trip_fee + slippage_cost`
- `break_even_ticks = round_trip_cost / tick_value`
- `break_even_points = break_even_ticks * tick_size`
