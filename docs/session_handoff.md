# Session Handoff
Updated: 2026-03-09 17:12 UTC

## Goal
- Design a deep telemetry architecture that measures real context cost, long-conversation drift, and improvement outcomes so future agent/process optimization can be systematic instead of proxy-only.

## Task Request Contract
- Objective: produce a durable telemetry design that separates direct context-consumption signals from process-quality proxies and explains how to instrument long conversations, summaries, file reads, planning drift, execution behavior, and final outcomes.
- In Scope: capture the current telemetry baseline and its blind spots; design telemetry layers, event schema, IDs, rollups, and storage boundaries; account for long chats, summary lineage, and context-loss detection; define derived metrics, anti-gaming guardrails, rollout phases, and acceptance checks; record the result in an ADR plus traceability artifacts.
- Out of Scope: implementing the full telemetry pipeline, changing model/provider APIs, rewriting historical ledgers, or replacing the existing process-governance system in this slice.
- Constraints: keep the design repository-native and mechanically auditable; optimize for future implementation rather than abstract theory; avoid relying on raw chat transcript retention as the main observability source; preserve privacy/minimization by default and store counts/hashes/references before raw content whenever possible.
- Done Evidence: one ADR captures architecture, schema, phases, risks, and metrics; plans and memory point to the design as the new source of truth; validators for handoff/plans/memory pass and lean gate stays green.
- Priority Rule: measurement truth beats convenience; if a metric can be gamed or does not distinguish direct context cost from outcome quality, it must be called out as a proxy rather than treated as a primary KPI.

## Current Delta
- Captured the current telemetry baseline and its main blind spots around direct context cost and long-conversation drift.
- Added an ADR that defines layered telemetry for task, turn, context acquisition, summary lineage, execution, and outcome signals.
- Separated direct context-cost metrics from outcome proxies and documented anti-gaming guardrails.
- Defined long-conversation observability through summary or compaction lineage, recall checks, and handoff refresh semantics.
- Recorded phased rollout so implementation can start small without losing architectural coherence.

## First-Time-Right Report
1. Confirmed coverage: task lifecycle telemetry, context-budget workflow, process reports, quality scorecards, and long-conversation risk are all included in the design scope.
2. Missing or risky scenarios: direct token-level telemetry may be unavailable in some tool paths; long chats can hide loss through summaries instead of obvious failures; naive “smaller context is always better” metrics can incentivize under-reading.
3. Resource/time risks and chosen controls: build the design around layered events and derived rollups, keep direct-cost metrics separate from outcome proxies, and define rollout in phases so implementation can start small without losing architectural coherence.
4. Highest-priority fixes or follow-ups: establish the telemetry model and long-conversation semantics first, then implement capture points, then connect governance thresholds and dashboards to the new direct-cost layer.

## Repetition Control
- Max Same-Path Attempts: 2
- Stop Trigger: two consecutive design edits still leave long-conversation handling or direct-context metrics undefined at the schema level.
- Reset Action: stop editing prose only, extract the missing concern into an explicit capability block with event names, inputs, outputs, and rollout phase.
- New Search Space: (1) task lifecycle events, (2) turn and summary lineage events, (3) file-read and tool-output cost signals, (4) rollup/KPI model, (5) governance/dashboard consumers.
- Next Probe: inventory the current telemetry surface, then map it into a layered event model and call out the gaps for long conversations and real context cost.

## Task Outcome
- Outcome Status: completed
- Decision Quality: correct_first_time
- Final Contexts: CTX-OPS, CTX-API-UI, CTX-CONTRACTS
- Route Match: matched
- Primary Rework Cause: none
- Incident Signature: none
- Improvement Action: architecture
- Improvement Artifact: docs/architecture/adr/0004-context-telemetry-observability.md
- Linked Plan ID: P1-CONTEXT-TELEMETRY-064

## Blockers
- None.

## Next Step
- Use the ADR as the source of truth for Phase 1 implementation: direct context-acquisition events, turn boundaries, and summary-lineage capture.

## Validation
- `powershell -ExecutionPolicy Bypass -File scripts/worktree_guard.ps1 -Action Check`
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/validate_plans.py`
- `python scripts/validate_agent_memory.py`
- `python scripts/run_lean_gate.py`
