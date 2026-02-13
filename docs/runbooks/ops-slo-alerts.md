# Ops SLO Alerts Runbook

## Scope
Interpretation and response workflow for `GET /api/v2/ops/slo` alerts.

## Endpoints
- `GET /api/v2/ops/health`
- `GET /api/v2/ops/slo`

## Alert matrix
1. `PRETRADE_LATENCY_HIGH`
- Trigger: `api.v2_pretrade_check.latency_ms.p95 > 1500`.
- Action: inspect ISS transport diagnostics and `events_15m.pretrade_degraded`.

2. `ACTION_LATENCY_HIGH`
- Trigger: `api.v2_signals_actions.latency_ms.p95 > 800`.
- Action: inspect DB write latency and idempotency replay load.

3. `EXECUTION_REJECTION_SPIKE`
- Trigger: `events_15m.execution_rejections_fail_closed >= 5`.
- Action: verify pretrade degradation and fail-closed policy path.

4. `PRETRADE_FAILURE_SPIKE`
- Trigger: `events_15m.pretrade_failures >= 10`.
- Action: inspect gate reasons (`block|check`), quote availability, and sync diagnostics.

5. `AUTO_UNWIND_ERRORS`
- Trigger: `events_15m.auto_unwind_errors >= 1`.
- Action: run `POST /api/v2/policies/auto-unwind/run` with `dry_run=true`, then inspect `errors[]`.

## Response sequence
1. Confirm service liveness:
- `GET /api/v2/ops/health`.
- If health is `503`, treat as platform incident first.
2. Pull current SLO payload:
- `GET /api/v2/ops/slo`.
3. For each alert in `alerts[]`, map to affected pipeline:
- `v2_pretrade_check`
- `v2_signals_actions`
- `v2_auto_unwind_run`.
4. Cross-check 15m counters vs expected thresholds in `slo_targets`.
5. Capture evidence (UTC timestamp + payload excerpt) before remediation.

## Investigative pivots
1. Pretrade path:
- Review `events_15m.pretrade_degraded` and `events_15m.pretrade_errors`.
- Sample `POST /api/v2/pretrade/check` on representative pairs.
2. Signal action path:
- Retry with deterministic `idempotency_key`.
- Inspect `GET /api/v2/signals/executions` for duplicate/blocked patterns.
3. Auto-unwind path:
- Run dry-run and compare candidates with active open-imbalance rows.

## Escalation
- P1: `AUTO_UNWIND_ERRORS` or repeated `EXECUTION_REJECTION_SPIKE` during active session.
- P2: sustained latency alerts > 30 minutes.
- P3: transient spikes resolved within one monitoring window.

## Closure criteria
1. `alerts[]` is empty for two consecutive checks (>= 15 minutes apart), or only low-severity transient warnings remain.
2. Incident timeline and remediation steps captured in `docs/planning/product-decisions.md`.
