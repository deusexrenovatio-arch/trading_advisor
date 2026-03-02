# Product Decisions Log

## 2026-02-13
- Decision: adopt workspace IA (`Trade Console`, `Research Lab`, `News Intelligence`, `Portfolio Control`).
- Why: reduce tab sprawl and keep task-focused operator context.
- Scope: frontend navigation + v2 API surfaces.

## 2026-02-13
- Decision: introduce `/api/v2/*` contract while preserving `/api/*` adapters.
- Why: contract-first evolution with backward compatibility.
- Sunset: v1 deprecation after two releases.

## 2026-02-13
- Decision: treat `ack` as first-class execution event.
- Why: auditable bridge between bot acknowledgment and manual execution details.

## 2026-02-13
- Decision: enable fail-closed execution through feature flag (`ui.ff_fail_closed_execution`) with privileged override.
- Why: prevent accidental entries when pretrade context is missing or ISS is degraded.
- Scope: `POST /api/v2/signals/{signal_id}/actions`, runbooks, risk policy.

## 2026-02-13
- Decision: use policy endpoint for stale one-leg imbalance auto-remediation.
- Why: reduce operational exposure from unmatched leg execution.
- Scope: `POST /api/v2/policies/auto-unwind/run` + `LEG_IMBALANCE_TIMEOUT` audit trail.

## 2026-02-13
- Decision: expose ops runtime observability as first-class v2 API.
- Why: enforce explicit SLO monitoring for pretrade latency, execution rejection spikes, and auto-unwind errors.
- Scope: `GET /api/v2/ops/health`, `GET /api/v2/ops/slo`, KPI/runbook updates.

## 2026-02-13
- Decision: split delivery into atomic commit series and keep release notes in strict patch-note format.
- Why: improve reviewability, rollback safety, and operational traceability.
- Scope:
  - Commit order: `contracts/config -> backend/domain -> frontend -> tests -> docs`.
  - Patch notes format: `Summary`, `Changed`, `Verification`, `Risk/Rollback`.

## 2026-03-02
- Decision: run component-first product coverage review as baseline planning artifact.
- Why: user value and acceptance quality degrade when requirements are tracked only by endpoint groups, not by end-to-end workspace journey.
- Scope:
  - Primary component order: `platform -> decisions -> market/signals -> research -> news -> portfolio -> ops/integrations`.
  - Scenario framing: `primary + edge + negative + interruption` per component.

## 2026-03-02
- Decision: prioritize idempotent operator action path and risk-gated commit path as P0 documentation outcomes.
- Why: execution safety and duplicate protection are more business-critical than adding new UI surface area.
- Scope:
  - Require explicit idempotency expectations in UI action scenarios.
  - Require explicit rebalance commit guard expectations when risk checks fail.

## 2026-03-02
- Decision: close action-safety gaps in implementation immediately after review (not defer to a later sprint).
- Why: P0 operator safety gaps were contract violations (`idempotency_key` required) and fail-safe violations (commit allowed despite failed risk gate).
- Scope:
  - UI write actions now generate/send `idempotency_key` for Signals and Decisions.
  - Portfolio rebalance commit now blocks on `max_positions` risk-gate failure.
  - Forward workspace now supports run start from UI via `POST /api/forward/start`.
