# Signal Action Audit Runbook

## Scope
Incident handling for signal actions (`ack|enter|exit|hold_open`) and audit discrepancies.

## Primary artifacts
- API:
  - `GET /api/v2/signals/active`
  - `POST /api/v2/signals/{signal_id}/actions`
  - `POST /api/v2/policies/auto-unwind/run`
  - `GET /api/v2/ops/slo`
  - `GET /api/v2/signals/executions`
- Storage:
  - `signal_executions` table
  - `data/decisions/decision_actions.jsonl`
  - `data/decisions/execution_requests.jsonl`

## Triage checklist
1. Identify `signal_id`, `entity_ref`, `idempotency_key`.
2. Verify action persistence in `signal_executions`.
3. Confirm lifecycle transition in `/api/v2/signals/active`.
4. Compare with decision projection (`/api/v2/decisions/view`) when decision context exists.
5. Check duplicates by `idempotency_key` in action notes.

## Common failure modes
- Duplicate submit from UI/bot race.
- Missing pair context for stale `signal_id`.
- Action persisted but lifecycle not refreshed due to stale run snapshot.
- Entry blocked by fail-closed policy (`ISS_DEGRADED_FAIL_CLOSED`, `PRETRADE_NOT_CONFIRMED`).
- One-leg execution remains open past timeout and needs auto-unwind.

## Recovery actions
- Duplicate submit:
  - Return existing execution event, do not write new row.
- Stale signal:
  - Re-fetch active set, require explicit stock/future override for manual repair.
- Projection mismatch:
  - Trigger signal refresh and compare run timestamps.
- Fail-closed block:
  - Verify pretrade status/degradation context.
  - Apply privileged override only with explicit reason and audit.
- Stale leg imbalance:
  - Run `POST /api/v2/policies/auto-unwind/run` (`dry_run` first, then execute).

## Escalation
- P1: Wrong lifecycle blocks/permits execution.
- P2: Duplicate action records without execution impact.
- P3: Missing non-critical metadata in notes.
