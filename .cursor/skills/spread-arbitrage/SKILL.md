---
name: spread-arbitrage
description: Deterministic spread arbitrage checklist and JSON plan template. Use for pair-spread strategy design, rechecks, and pre-push validation when spread logic changes. Co-use with moex-instruments-costs, risk-profile-gates, and news-geopolitics-filter.
---

# Spread Arbitrage Checklist

## Purpose
Audit spread arbitrage prototypes for data integrity, liquidity, and risk constraints before enabling strategies.

## Skill dependencies and lifecycle gates
- Cost phase: run `moex-instruments-costs` for each leg before spread checks.
- Risk phase: run `risk-profile-gates` for portfolio and execution constraints.
- Event-risk phase: run `news-geopolitics-filter` when market/event risk can invalidate spread entries.
- Recheck/pre-push phase: rerun spread audit whenever hedge ratio, thresholds, or holding constraints change.

## Required inputs
- `leg_a` (`instrument`, `tick_size`, `tick_value`, `liquidity`)
- `leg_b` (`instrument`, `tick_size`, `tick_value`, `liquidity`)
- `hedge_ratio`
- `entry_zscore`
- `exit_zscore`
- `stop_zscore`
- `max_holding_minutes`
- `cost_model` (per-leg round-trip costs)

## Deterministic checks
- Both legs meet minimum configured liquidity.
- `hedge_ratio > 0`.
- `entry_zscore > exit_zscore` and `stop_zscore >= entry_zscore`.
- `max_holding_minutes` is within `[1, 480]`.
- Total round-trip cost is below expected mean-reversion move.

## Output JSON template
```json
{
  "spread_strategy": {
    "pair": {
      "leg_a": "RIH5",
      "leg_b": "SiH5",
      "hedge_ratio": 0.8
    },
    "entry_zscore": 2.0,
    "exit_zscore": 0.5,
    "stop_zscore": 3.0,
    "max_holding_minutes": 120
  },
  "audit_result": {
    "passed": true,
    "checks": [
      {
        "id": "liquidity_min",
        "passed": true,
        "message": "Both legs meet minimum liquidity."
      }
    ],
    "actions": []
  }
}
```
