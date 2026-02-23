---
name: ui-decision-log
description: UI projection and deterministic checks for mapping decision_log into decision_view. Use when changing projection fields, filters, or decision contracts. Co-use with trading-ui-dashboard for implementation and frontend-behavior-check for recheck/pre-push validation.
---

# UI Decision Log Projection

## Purpose
Create a UI-friendly `decision_view` from canonical `decision_log` with strict field mapping and traceability.

## Skill dependencies and lifecycle gates
- Build phase: pair with `trading-ui-dashboard` for table/filter/drill-down behavior.
- Recheck phase: run `frontend-behavior-check` for API + proxy + UI expectations.
- Pre-push phase: ensure `docs/DEV_WORKFLOW.md` required checks pass after projection updates.


## Repository governance baseline (mandatory)
- Follow `docs/workflows/skill-governance-sync.md` for mandatory repository gates (worktree guard, lean loop, plans/memory/handoff, pre-push blockers, repeated-issue escalation).
- Keep this skill focused on domain workflow; do not duplicate repository governance details here.

## Required inputs
- `decision_log` (validated against `contracts/decision-log.schema.json`)
- `ui_filters` (list of filters to expose)
- `ui_columns` (ordered display list for table)

## Deterministic checks
- `decision_id` is present and copied to `decision_view.decision_id`.
- `decision_view.schema_version` matches current schema.
- `cost_summary` fields exist and match `decision_log.cost_model`.
- UI filters include: `strategy_type`, `primary_instrument`, `risk_state`, `created_at`, `news_severity`.
- Drill-down link points to `decision_log` by `decision_id`.
- For `/api/v2/decisions/view`, rows include backend-owned references:
  - `decision_ref`
  - `execution_ref`
  - `projection_source`

## Output JSON template
```json
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
## Mandatory pre-push guidance
- Run `python scripts/sync_architecture_map.py --check` when boundaries or integrations are touched.
- Run required checks from `docs/DEV_WORKFLOW.md` for touched areas; treat failures as blockers.
- If contracts/registry/docs changed, update source-of-truth artifacts before push and keep notes in AGENTS or PR summary.
