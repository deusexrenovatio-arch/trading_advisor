# Decision State Machine v2

## Scope
This contract defines backend-owned state transitions for signal, decision, and execution flows.
UI clients must render these states and must not derive alternative business states locally.

## Signal Lifecycle States

States:
- `candidate`
- `blocked`
- `ready`
- `acknowledged`
- `entered`
- `hold_open`
- `exit_ready`
- `closed`
- `rejected`

Transitions:
1. `candidate -> blocked` on pretrade/risk gate block.
2. `candidate -> ready` on all mandatory gates pass.
3. `ready -> acknowledged` on `ack` action.
4. `ready -> entered` on `enter` action with confirmed execution.
5. `entered -> hold_open` while position remains open and no exit trigger.
6. `hold_open -> exit_ready` when strategy emits exit condition.
7. `exit_ready -> closed` on `exit` action and confirmed close execution.
8. `candidate|ready|blocked -> rejected` on explicit reject decision.
9. `ready -> blocked` on fail-closed execution policy (`ISS_DEGRADED_FAIL_CLOSED` or `PRETRADE_NOT_CONFIRMED`).
10. `hold_open|exit_ready -> closed` on auto-unwind policy action (`reason_code=LEG_IMBALANCE_TIMEOUT`).

## Decision Actions (v2)

Endpoint: `POST /api/v2/decisions/{decision_id}/actions`

Allowed actions:
- `APPROVE`
- `HOLD`
- `REJECT`
- `EXECUTE`
- `CLOSE`

Action semantics:
1. `APPROVE`: mark decision as approved for operator flow.
2. `HOLD`: keep decision pending with explicit reason.
3. `REJECT`: terminal rejection for current decision context.
4. `EXECUTE`: enqueue execution request.
5. `CLOSE`: enqueue close request for open exposure.

## Idempotency

Rules:
1. Every action may include `idempotency_key`.
2. Duplicate `idempotency_key` for same `decision_id` returns `status=duplicate`.
3. Action and execution audit rows preserve the same `idempotency_key`.

## Audit Projection

Persisted artifacts:
1. `decision_actions.jsonl`: operator action facts.
2. `execution_requests.jsonl`: execution request facts.
3. `decision_view` projection reads latest action/execution by `decision_id`.
4. `GET /api/v2/decisions/view` exposes backend-owned `decision_ref` and `execution_ref`
   with latest audit linkage (`action_id`, `request_id`, `idempotency_key`, timestamps).
5. Projection response includes `projection_source` (`jsonl|db|jsonl_fallback`) for rollout diagnostics.
6. Decision projection write path is synchronized: new `decision_view` appends are write-through to DB projection.

Compatibility:
1. v1 endpoint `POST /api/decisions/{decision_id}/action` is an adapter on v2 logic.
2. Adapter is retained for two releases, then removed.

## Policy Extensions (Sprint 4)

Fail-closed execution:
1. Config flag: `ui.ff_fail_closed_execution`.
2. Entry action (`enter`) is blocked when pretrade status is missing/not-pass or ISS is degraded.
3. Explicit override is allowed only for privileged source (`system|telegram`) with an audit reason.

Auto-unwind:
1. Endpoint: `POST /api/v2/policies/auto-unwind/run`.
2. Candidate selection: open pair with leg imbalance older than `timeout_sec`.
3. Action: submit `exit` with `reason_code=LEG_IMBALANCE_TIMEOUT`, idempotent by pair + last execution timestamp.
