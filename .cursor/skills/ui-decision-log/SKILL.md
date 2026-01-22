---
name: ui-decision-log
description: UI projection and checks for decision_log to decision_view.
---

# UI Decision Log Projection

## Purpose
Create a UI-friendly decision_view from the canonical decision_log with strict
field mapping and traceability.

## Required inputs
- decision_log (validated against decision-log.schema.json)
- ui_filters (list of filters to expose)
- ui_columns (ordered list for table display)

## Deterministic checks
- decision_id is present and copied to decision_view.decision_id.
- decision_view.schema_version matches current schema.
- cost_summary fields exist and match decision_log.cost_model.
- UI filters include: strategy_type, primary_instrument, risk_state, created_at, news_severity.
- Drilldown link must point to decision_log by decision_id.

## Output JSON template
```
{
  "decision_view": {
    "schema_version": "1.0.0",
    "decision_view_id": "view-0001",
    "decision_id": "decision-0001",
    "created_at": "2025-01-21T12:00:00Z",
    "strategy_type": "mixed",
    "primary_instrument": "RTS",
    "action": "approve",
    "risk_state": "green",
    "risk_summary": "All limits within bounds.",
    "news_severity": "low",
    "cost_summary": {
      "round_trip_cost": 33.6,
      "break_even_ticks": 3.36,
      "break_even_points": 0.0336
    },
    "key_features": [
      { "name": "carry_spread", "value": 0.8, "units": "pct" }
    ],
    "allocations": [
      { "instrument": "RIH5", "side": "long", "target_weight": 0.25 }
    ],
    "links": {
      "decision_log": "decision-0001",
      "input_snapshots": ["snap-iss-001", "snap-quik-002"]
    }
  }
}
```
