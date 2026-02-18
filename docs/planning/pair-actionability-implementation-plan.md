# Entity-Centric Signal Actionability: Architecture and Implementation Plan

## Product Intent
Operator must always see what is usable now, with explicit reasons when something is not usable.
This must work for:
- pair entities (`stock+future`),
- single-instrument entities (`stock` or `future`),
- multi-source evidence that can conflict.

Primary UX expectations:
- actionable opportunities are not hidden by technical lifecycle artifacts;
- `hold_open` exists only as a position overlay from execution facts;
- contradictions across sources are deterministic and explainable;
- Telegram delivery is useful and non-spammy.

## Architecture Revision (Target)

### 1. Canonical Entity Identity Layer
Responsibility:
- normalize source identifiers to canonical `EntityRef`.
- support `entity_type=pair|instrument`.

Output:
- stable `entity_ref` for downstream composition and action routing.

### 2. Evidence Ingestion Layer
Responsibility:
- ingest source-specific outputs (TA, FA, News, Risk, Liquidity, Model).
- normalize each fact to `SignalEvidenceItem`.

Rules:
- each evidence item must include source kind, stance, confidence, freshness, reason codes.
- stale evidence is downgraded or neutralized by policy.

### 3. Evidence Composer
Responsibility:
- aggregate evidence per entity and horizon.
- compute `support_weight_total`, `oppose_weight_total`, `conflict_score`, `veto_active`.

Output:
- `SignalEvidenceSummary` + selected evidence slice for UI detail.

### 4. Deterministic Policy Engine
Responsibility:
- evaluate ordered gates and produce final policy state.
- precedence is strict and auditable.

Gate precedence v1:
1. `risk_profile`
2. `news_geopolitics`
3. `liquidity`
4. `execution_feasibility`
5. `source_freshness`
6. `portfolio_limits`
7. `venue_constraints`

Decision rule:
- any `block` -> `policy=block`
- else any `review` -> `policy=review`
- else any `reduce` -> `policy=reduce`
- else `policy=allow`

Output:
- `SignalPolicyOutcome` including `precedence_version`, `applied_gate_id`, `gate_trace`.

### 5. Intent Manager
Responsibility:
- maintain `intent_id` lifecycle independent from historical `signal_id`.
- apply TTL and consumption semantics.

Intent lifecycle:
- `none -> active -> out_of_range -> active(repriced) -> consumed|expired|superseded`

Consumption rule:
- intent is consumed only by explicit operator action (`ack` or `enter`) for this intent.

### 6. Position Overlay
Responsibility:
- derive `position_state` strictly from execution ledger (`enter` minus `exit`).
- publish `hold_open` overlay independent from entry policy.

Important:
- open position does not automatically suppress a fresh actionable enter intent.

### 7. Projection Builder
Responsibility:
- build canonical `SignalActionabilityV2` row per entity.
- compute derived `actionability_state` from axes.

Axes:
- `policy_state`, `intent_state`, `position_state`, `execution_state`, `delivery_state`.

Derived state examples:
- `actionable_enter`, `review_entry`, `enter_out_of_range`, `actionable_enter_repriced`,
  `hold_open`, `actionable_exit`, `blocked_entry`, `inactive`.

### 8. Delivery Orchestrator (Telegram/UI)
Responsibility:
- consume canonical projection.
- enforce anti-spam and cooldown.

Delivery rules:
- one enter message per fingerprint/revision;
- one out-of-range update per fingerprint;
- new enter message only for new revision/fingerprint;
- suppressed reasons are explicit (`intent_consumed`, `intent_expired`, `out_of_range`, ...).

### 9. Action Command API
Responsibility:
- accept operator commands by entity + intent.
- enforce idempotency and fail-closed behavior.

Canonical endpoint:
- `POST /api/v2/entities/{entity_type}/{entity_id}/signals/actions`

Compatibility endpoint:
- `POST /api/v2/pairs/{pair_id}/actions` (adapter only).

## Why this architecture matches expectations
- Usability-first view: entity projection answers "can I use this now?".
- Source conflicts are first-class: not hidden in a single score.
- Operator control is explicit: usage/consumption only on deliberate action.
- Trading risk is deterministic: risk/news gates can veto even strong TA/FA support.
- Telegram behavior is stable under volatility and repricing.

## Implementation Plan

### Phase 0: Contract Freeze and Rulebook
Deliverables:
- finalize `SignalActionabilityV2`, axes model, policy precedence, transition table.
- freeze enums for policy/gates/states.
Acceptance:
- contract reviewed and approved by backend, UI, and bot owners.

### Phase 1: Canonical Data Structures
Deliverables:
- backend domain models for `EntityRef`, `EvidenceItem`, `PolicyOutcome`, `IntentState`.
- storage schema/extensions for intent revisions and gate trace.
Acceptance:
- deterministic serialization and backward-compatible persistence.

### Phase 2: Source Normalizers
Deliverables:
- adapters: TA, FA, News, Risk/Liquidity.
- common evidence normalization pipeline.
Acceptance:
- mixed-source entities produce valid evidence arrays with freshness metadata.

### Phase 3: Composer + Policy Engine
Deliverables:
- evidence composer with conflict/veto logic.
- ordered gate evaluator with precedence v1.
Acceptance:
- golden scenarios (TA+FA support vs adverse news) produce deterministic `block`.

### Phase 4: Intent Manager + Repricing
Deliverables:
- intent lifecycle service with TTL, consumption, supersession.
- repricing path for `enter_out_of_range -> actionable_enter_repriced`.
Acceptance:
- intent does not disappear silently;
- repricing creates new revision/fingerprint.

### Phase 5: Canonical Projection API
Deliverables:
- `GET /api/v2/signals/actionability`.
- pair-view adapter `GET /api/v2/pairs/actionability`.
Acceptance:
- feed contains both `pair` and `instrument` entities with stable fields.

### Phase 6: Canonical Action API
Deliverables:
- `POST /api/v2/entities/{entity_type}/{entity_id}/signals/actions`.
- idempotency + fail-closed + compatibility adapter for pair actions.
Acceptance:
- repeated idempotency key returns `duplicate`;
- intent-aware actions update projection consistently.

### Phase 7: Telegram and UI Migration
Deliverables:
- Telegram worker uses canonical feed and action API.
- UI shows axes + policy reasons + evidence summary.
Acceptance:
- no spam regressions;
- operator sees explicit reason for any blocked/review state.

### Phase 8: Cutover and Legacy Decommission
Deliverables:
- feature flags switched to canonical endpoints by default.
- legacy endpoints moved to compatibility mode only.
Acceptance:
- parity metrics stable for agreed burn-in window.

## Acceptance Scenarios to Prevent Future Dead-Ends
1. TA supports enter, FA supports, high-severity news opposes -> `policy=block`, row visible with reason.
2. `policy=review` -> row visible, no auto-enter delivery, explicit manual confirmation path.
3. `open position + fresh actionable enter intent` -> `hold_open` overlay and enter intent both visible.
4. Out-of-range path -> one notification, repricing yields new fingerprint and one new enter message.
5. Ack without enter -> intent consumed, position unchanged.
6. Risk limit breach intraday -> immediate block regardless of source support.
7. Stale evidence only -> `review` or `blocked_entry` per configured freshness policy.
8. Pair and instrument entities behave identically under action API semantics.

## KPI and Go/No-Go
Go-live KPIs:
- 0 unexplained suppressions in projection payload.
- 0 duplicate Telegram out-of-range messages per fingerprint.
- >= 99% deterministic replay parity for policy outcome over fixed fixtures.
- < 1 minute projection freshness lag in normal mode.

No-go triggers:
- non-deterministic policy decisions for identical snapshots;
- missing reason codes for blocked/review states;
- hold/open state mismatch with execution ledger.
