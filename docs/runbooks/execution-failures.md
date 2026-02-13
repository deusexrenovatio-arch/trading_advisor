# Execution Failures Runbook

## Scope
Operational troubleshooting for failed or inconsistent signal actions (`ack|enter|exit|hold` -> execution events).

## Primary checks
1. Get current signal context:
- `GET /api/v2/signals/active`
2. Inspect recent execution events:
- `GET /api/v2/signals/executions?stock=...&future=...&limit=20`
3. Validate action write path:
- `POST /api/v2/signals/{signal_id}/actions`
4. Review decision projection when relevant:
- `GET /api/v2/decisions/view?limit=...`

## Failure signatures and actions
1. HTTP `409` with `status=blocked` and `error=fail_closed_execution`:
- Expected behavior in fail-closed mode.
- Confirm reason code:
  - `ISS_DEGRADED_FAIL_CLOSED`
  - `PRETRADE_NOT_CONFIRMED`
  - `PRETRADE_BLOCKED`.
- Verify no new execution row was created for this attempt.
2. `status=duplicate`:
- Reused `idempotency_key`.
- Validate that returned `order_id` / execution id points to existing event.
3. `404 not_found` on action submit:
- Stale or unknown `signal_id`.
- Re-fetch active set and retry with fresh `signal_id` (or explicit `stock/future` for operator repair flow).
4. Persistent leg imbalance:
- In `GET /api/v2/signals/active` row has `position_leg_imbalance=true`.
- Check `position_open_stock_legs` vs `position_open_future_legs`.

## Auto-unwind remediation
1. Dry run:
- `POST /api/v2/policies/auto-unwind/run` with `{ "dry_run": true }`.
2. Live run:
- `POST /api/v2/policies/auto-unwind/run` with `{ "timeout_sec": <policy>, "actor_id": "<owner>" }`.
3. Validate summary:
- `candidate_count`, `triggered_count`, `duplicate_count`, `blocked_count`, `error_count`.
4. Re-check pair state in `GET /api/v2/signals/active`.

## Common root causes
1. Concurrent UI/bot submit with same semantics but different keys.
2. Stale signal snapshot between operator action and execution.
3. Transport degradation causing pretrade to remain unconfirmed.
4. Partial two-leg fills with delayed unwind.

## Escalation
1. `P1`: valid exits blocked repeatedly or imbalance risk grows.
2. `P2`: auto-unwind cannot close stale imbalance within policy timeout.
3. `P3`: metadata/audit mismatch but execution state is consistent.

## Post-incident checklist
1. Attach sample payloads/responses (blocked, duplicate, recovered).
2. Record action timeline and owner decisions in `docs/planning/product-decisions.md`.
