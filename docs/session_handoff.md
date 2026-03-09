# Session Handoff
Updated: 2026-03-09 16:28 UTC

## Goal
- Finish integration of the H4A live/manual hardening slice into `codex/signals_engine` by restoring the legacy API compatibility needed for the repository pre-push gate and opening the PR.

## Task Request Contract
- Objective: complete the PR-ready integration of the H4A live/manual hardening slice by fixing the remaining repository-level compatibility blockers uncovered by the full pre-push suite.
- In Scope: keep the completed H4A hardening changes intact; restore legacy `/api/signals/execute`, `/api/signals/executions`, and `/api/signals/active` compatibility where the old API still expects `ack`/`enter` semantics; narrow operator-event fallback so exact fingerprint intent consumption still works without leaking `signal_used` into current `hold_open` rows; remove the task-specific coupling from the news operational contract test; push the branch and open a PR into `codex/signals_engine`.
- Out of Scope: changing the approved H4A lifecycle semantics in v2, rolling back Telegram post-fill follow-up behavior, reintroducing unsafe live-routing paths, or weakening repository pre-push gates.
- Constraints: preserve non-destructive git flow and PR-only integration; keep v2/H4A canonical actions authoritative in runtime/audit paths; limit legacy compatibility shims to v1 endpoints and replay/projection logic that the full test suite still covers; keep `docs/session_handoff.md` task-specific rather than turning it into a permanent operational reference.
- Done Evidence: full blocking test set for legacy signal API and news operational contract passes; branch pushes to origin; PR targeting `codex/signals_engine` is opened with verification evidence.
- Priority Rule: do not trade away canonical H4A/v2 correctness to satisfy legacy expectations; restore compatibility only at explicit v1 or historical-replay boundaries.

## Current Delta
- live-routing blocks mini roots, mini/full duplicates, and correlated-cluster overfill before publication.
- synthetic-history runtime adapter cannot promote legacy non-enter rows into actionable enters.
- Telegram drives the post-fill H4A operator loop with stage-specific `Confirm` and `Manual override` actions.
- contract/docs/acceptance traces keep `mark_viewed` canonical while preserving `ack` as a compatibility alias.
- operator event projection was extracted from `src/moex_carry/ui/app.py` into a dedicated helper to reduce structural pressure.
- the legacy compatibility patch now restores v1 execute/executions behavior without rolling back canonical v2/H4A actions.
- legacy `ack` once again consumes old pending intent by exact fingerprint, while `hold_open` rows no longer inherit `signal_used=true` from pair fallback.

## First-Time-Right Report
1. Confirmed coverage: the remaining work is limited to legacy v1 compatibility and test-contract hygiene; canonical H4A hardening remains in place.
2. Missing or risky scenarios: a broad compatibility rollback could silently undo the new lifecycle semantics; pair-level operator fallback can over-apply `signal_used`; task-specific docs can create false blockers if operational tests depend on them.
3. Resource/time risks and chosen controls: patch only the legacy API adapter and replay/projection boundary, keep canonical v2 action normalization untouched, and prove the fix with the exact failing tests before rerunning the full push gate.
4. Highest-priority fixes or follow-ups: restore pushability first, open the PR second, and leave any further module decomposition as a separate follow-up.

## Repetition Control
- Max Same-Path Attempts: 2
- Stop Trigger: two consecutive compatibility patches still leave the same five signal API tests or the same news operational contract test failing.
- Reset Action: stop editing the same normalization branch, inspect where exact fingerprint matching is lost versus where pair fallback is applied, and isolate the legacy/v1 display adapter from canonical runtime normalization.
- New Search Space: (1) legacy action request normalization, (2) v1 executions endpoint serialization, (3) operator-event registration for nested/direct ack notes, (4) pair fallback in active-signal projection, (5) tests that incorrectly depend on task-specific docs.
- Next Probe: first restore exact legacy storage/display semantics for v1 endpoints, then fix ack-driven intent consumption on exact fingerprints, then trim the news operational contract test to stable docs only.

## Task Outcome
- Outcome Status: in_progress
- Decision Quality: pending
- Final Contexts: CTX-STRATEGY, CTX-API-UI, CTX-OPS
- Route Match: pending
- Primary Rework Cause: none
- Incident Signature: none
- Improvement Action: architecture
- Improvement Artifact: src/moex_carry/ui/operator_execution_projection.py
- Linked Plan ID: P1-H4A-LIVE-062

## Blockers
- No code-level blocker remains after the legacy compatibility patch and full local verification.
- Remaining work is procedural: push the branch and open the PR into `codex/signals_engine`.

## Next Step
- Push `codex/h4a-live-hardening` to origin and open the PR into `codex/signals_engine`.

## Validation
- `powershell -ExecutionPolicy Bypass -File scripts/worktree_guard.ps1 -Action Check`
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/validate_api_v2_contract_parity.py`
- `python scripts/validate_quality_scorecards.py`
- `python scripts/run_lean_gate.py`
- `pytest tests/test_signal_api.py -q -k "test_signals_execute_normalizes_hold_open_action_to_enter or test_signals_executions_endpoint_normalizes_hold_open_action or test_signals_active_marks_signal_used_from_nested_ack_note or test_signals_active_pending_enter_stops_after_explicit_use or test_signals_active_flat_pending_enter_stops_after_explicit_use"`
- `pytest tests/test_news_operational_contract.py -q`
- `pytest`
- `cmd /c npm --prefix ui-web ci`
- `cmd /c npm --prefix ui-web run lint`
- `cmd /c npm --prefix ui-web run build`
