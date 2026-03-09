# Session Handoff
Updated: 2026-03-09 15:34 UTC

## Goal
- Finish the remaining H4A live/manual hardening work by adding live-routing guards (`no-mini`, concentration, synthetic-promotion limits) and a Telegram post-fill operator loop that mirrors the approved H4A runbook.

## Task Request Contract
- Objective: finish the open acceptance items for H4A so that live selection is guarded before publication and every post-fill recalculation has an explicit Telegram-facing operator flow.
- In Scope: keep `H4A_CAP_OFF` as the active baseline; add no-mini hygiene and concentration routing before actionable publication; stop synthetic-history runtime adapter paths from promoting new actionable enters; enrich fill-state recalculation with H4A monitoring thresholds; implement Telegram post-fill messages, reminders, and operator deviation handling; update docs/tests/governance for the new flow.
- Out of Scope: redefining H4A trade-management semantics, reintroducing winner caps as a concentration workaround, building broker auto-routing, or adding a full portfolio optimizer beyond the deterministic routing guards needed for manual live use.
- Constraints: preserve non-destructive git flow; keep the existing lifecycle contract and one-release `ack` alias compatibility; treat `docs/runbooks/h4a-manual-execution-baseline.md` as the execution source of truth and `docs/signals-business-process.md` as the lifecycle source of truth; keep the routing layer deterministic and explainable; any Telegram interaction must still leave execution facts in the backend audit trail.
- Done Evidence: actionability/pair projection blocks mini-root live enters and enforces concentration caps before publication; runtime adapter no longer upgrades synthetic-history rows into actionable enters; H4A fill state exposes operator-ready post-fill levels and deadlines; Telegram worker sends dedicated post-fill messages and time-stop reminders and supports explicit post-fill operator deviation logging; targeted pytest suites pass; `python scripts/run_lean_gate.py` passes after changes.
- Priority Rule: H4A operator correctness and fail-closed live routing win over convenience; if a behavior would be ambiguous for a human operator, prefer explicit suppression or explicit Telegram instruction over silent permissiveness.

## Current Delta
- Closed in this task:
  - live-routing now blocks mini roots, mini/full duplicates, and correlated-cluster overfill before publication,
  - synthetic-history runtime adapter cannot promote legacy non-enter rows into actionable enters,
  - Telegram now drives the post-fill H4A operator loop with stage-specific `Confirm` and `Manual override` actions,
  - contract/docs/acceptance traces now describe `mark_viewed` as the canonical review action and keep `ack` only as a compatibility alias.
- Structural follow-up completed as part of the fix:
  - operator event projection was extracted from `src/moex_carry/ui/app.py` into a dedicated helper to bring the file back under the hard taste limit.

## First-Time-Right Report
1. Confirmed coverage: live-routing suppression, synthetic-promotion blocking, post-fill Telegram packet delivery, time-stop reminders, operator deviation logging, and regression coverage are all part of this slice.
2. Missing or risky scenarios: routing caps can accidentally hide open positions if applied at the wrong layer; Telegram post-fill reminders can spam if state dedup is weak; synthetic-promotion blocking can silently change live volume if applied only in UI but not in runtime history.
3. Resource/time risks and chosen controls: apply routing guards in one deterministic pre-projection pass, keep synthetic-promotion protection at the runtime-adapter source and reinforce it in actionability, deduplicate Telegram post-fill messages with explicit worker state, and validate with focused pytest plus lean gate before and after the patch.
4. Highest-priority fixes or follow-ups: stop unsafe signal publication first, then make post-fill operator actions explicit in Telegram, then sync docs and tests so the new workflow is explainable and replayable.

## Repetition Control
- Max Same-Path Attempts: 2
- Stop Trigger: two consecutive fixes still leave the same publication leak (mini/concentration/synthetic enter still reaches Telegram) or the same Telegram post-fill message repeats/misses on the same state transition.
- Reset Action: stop patching the same route or worker branch, extract the disputed decision into a dedicated helper with a narrow fixture, and replay the end-to-end state transition with a minimal row set.
- New Search Space: (1) runtime adapter override source, (2) pre-projection routing annotation, (3) final actionability delivery suppression, (4) Telegram worker broadcast state machine, (5) direct signal_execution_contract helper tests.
- Next Probe: annotate candidate rows with routing decisions before projection, then wire one post-fill Telegram notification path from `enter_filled` to worker output before adding reminders or override callbacks.

## Task Outcome
- Outcome Status: completed
- Decision Quality: correct_after_replan
- Final Contexts: CTX-STRATEGY, CTX-API-UI, CTX-OPS
- Route Match: matched
- Primary Rework Cause: none
- Incident Signature: none
- Improvement Action: architecture
- Improvement Artifact: src/moex_carry/ui/operator_execution_projection.py
- Linked Plan ID: P1-H4A-LIVE-062

## Blockers
- None.

## Next Step
- No implementation blocker remains in this slice. Next meaningful step is optional follow-on decomposition of large UI/runtime modules that still exceed target line budgets but are no longer hard blockers.

## Validation
- `powershell -ExecutionPolicy Bypass -File scripts/worktree_guard.ps1 -Action Check`
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/validate_api_v2_contract_parity.py`
- `python scripts/run_lean_gate.py`
- `pytest tests/test_api_v2.py tests/test_signal_cycle.py tests/test_telegram_worker.py -q`
