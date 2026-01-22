---
name: spread-arbitrage
description: Deterministic spread arbitrage checklist and JSON plan template.
---

# Spread Arbitrage Checklist

## Purpose
Audit spread arbitrage prototypes for data integrity, liquidity, and risk
constraints before strategies are enabled.

## Required inputs
- leg_a (instrument, tick_size, tick_value, liquidity)
- leg_b (instrument, tick_size, tick_value, liquidity)
- hedge_ratio
- entry_zscore
- exit_zscore
- stop_zscore
- max_holding_minutes
- cost_model (per-leg round-trip costs)

## Deterministic checks
- Both legs have liquidity >= configured minimum.
- hedge_ratio > 0.
- entry_zscore > exit_zscore and stop_zscore >= entry_zscore.
- max_holding_minutes between 1 and 480.
- Total round-trip cost < expected spread mean reversion move.

## Output JSON template
```
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
