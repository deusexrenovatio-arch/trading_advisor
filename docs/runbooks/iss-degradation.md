# ISS Degradation Runbook

## Scope
Incident response when ISS transport/quotes degrade and entry actions are blocked by fail-closed policy.

## Detection signals
1. Pretrade degradation:
- `POST /api/v2/pretrade/check` returns `degraded=true`.
- `advisory_reasons` contains `iss_transport_error`.
2. Entry blocked by policy:
- `POST /api/v2/signals/{signal_id}/actions` returns HTTP `409`.
- Payload contains:
  - `status=blocked`
  - `error=fail_closed_execution`
  - `reason_code=ISS_DEGRADED_FAIL_CLOSED` (or `PRETRADE_NOT_CONFIRMED` / `PRETRADE_BLOCKED`).
3. SLO alerts:
- `GET /api/v2/ops/slo` contains alerts:
  - `EXECUTION_REJECTION_SPIKE`
  - `PRETRADE_FAILURE_SPIKE`.

## First 10 minutes
1. Confirm platform health:
- `GET /api/v2/ops/health`.
- Check `checks.database.status=ok`.
2. Confirm incident scale:
- `GET /api/v2/ops/slo`.
- Check `events_15m.pretrade_degraded`, `events_15m.pretrade_failures`, `events_15m.execution_rejections_fail_closed`.
3. Validate on 2-3 representative pairs via `POST /api/v2/pretrade/check`.
4. Notify risk owner + operator channel with UTC timestamp and affected pairs.

## Triage tree
1. If only one pair is degraded:
- Treat as pair-level data issue.
- Keep fail-closed enabled.
2. If many pairs are degraded:
- Treat as transport outage/regression.
- Check current network path and fallback configuration (`moex.fallback_ips`).
3. If pretrade is healthy but entries still blocked:
- Verify action payload pretrade hints (`pretrade_status`, `pretrade.degraded`) and signal context freshness via `GET /api/v2/signals/active`.

## Controlled override policy
1. Override is allowed only for `source=system|telegram`.
2. Mandatory action payload fields:
- `fail_closed_override=true`
- `override_reason` or `reason_code`
- `idempotency_key`.
3. Audit validation:
- `GET /api/v2/signals/executions?stock=...&future=...`
- Verify `signal_executions.note` contains `fail_closed_override=true` and reason.

## Recovery
1. Pretrade returns stable non-degraded responses for at least 15 minutes.
2. `GET /api/v2/ops/slo` no longer reports critical spikes for the current window.
3. Re-run previously blocked entries without override where still relevant.

## Escalation criteria
1. `P1`: sustained global degradation > 15 minutes during active session.
2. `P1`: valid exits are blocked by policy.
3. `P2`: degradation isolated to subset of instruments > 30 minutes.
4. `P3`: transient spikes recovered within one 15m window.

## Post-incident
1. Record summary and decision trail in `docs/planning/product-decisions.md`.
2. Update `docs/release-notes.md` if policy/behavior was changed.
