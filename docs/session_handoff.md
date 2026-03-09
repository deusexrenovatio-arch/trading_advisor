# Session Handoff
Updated: 2026-03-09 11:15 UTC

## Goal
- Unblock the protected push for `codex/signals_engine` by fixing the remaining pre-push governance blockers.

## Task Request Contract
- Objective: remove the pre-push blockers that currently prevent `git push --force-with-lease origin codex/signals_engine`.
- In Scope: agent-context coverage for `src/moex_carry/signal_engine/*`, matching `docs/agent-contexts` sync, and minimal cohesive extractions to bring hard-limit files back under taste-invariant size caps.
- Out of Scope: relaxing the hard limits, large feature refactors, or unrelated behavior changes in strategy/news/runtime logic.
- Constraints: keep runtime behavior stable; prefer small file moves over semantic rewrites; preserve the completed rebase/governance recovery work; fix blockers in a way that satisfies existing validators rather than bypassing them.
- Done Evidence: `python scripts/validate_agent_contexts.py`, `python scripts/validate_taste_invariants.py`, `python scripts/run_lean_gate.py`, and successful `git push --force-with-lease origin codex/signals_engine`.
- Priority Rule: make the branch pushable with the smallest defensible code movement; correctness and gate compliance beat cosmetic cleanup.

## Current Delta
- The branch is already rebased onto current `origin/main`.
- Push is blocked by two gate classes.
- The first is unmapped `signal_engine` files in `validate_agent_contexts.py`.
- The second is hard size-limit failures in `config.py`, `telegram_worker.py`, and `ui/app_helpers_base.py`.
- The repository production news route remains `news_root_cycle`; this push-unblock work does not change that operating contract.
- Governance parity from the rebase recovery is already committed and must remain intact while fixing the push blockers.

## First-Time-Right Report
1. Confirmed coverage: context routing, matching docs, hard-limit file size fixes, and the retry push are in scope.
2. Missing or risky scenarios: moving helpers out of `telegram_worker.py` or `config.py` can accidentally change imports or defaults if the extraction crosses ownership boundaries.
3. Resource/time risks and chosen controls: use cohesive helper/config modules, keep external interfaces unchanged, and validate the exact blocking gates before retrying push.
4. Highest-priority fixes or follow-ups: map `signal_engine` first, then shrink the three hard-limit files, then rerun lean gate and retry the protected push.

## Repetition Control
- Max Same-Path Attempts: 2
- Stop Trigger: two extraction attempts still leave the same file above the hard limit or break the same validator.
- Reset Action: stop splitting the same file, inspect validator output plus import graph, and choose a different cohesive slice or ownership placement.
- New Search Space: (1) context-router/doc sync only, (2) config submodule extraction, (3) telegram state/helper extraction, (4) UI evidence/helper extraction.
- Next Probe: add `signal_engine` context coverage first and rerun `validate_agent_contexts.py` before touching the oversized files.

## Task Outcome
- Outcome Status: in_progress
- Decision Quality: pending
- Final Contexts: CTX-OPS, CTX-ORCHESTRATION, CTX-STRATEGY, CTX-API-UI
- Route Match: pending
- Primary Rework Cause: none
- Incident Signature: none
- Improvement Action: pending
- Improvement Artifact: pending
- Linked Plan ID: P1-PUSH-GATE-060

## Blockers
- None.

## Next Step
- Add `signal_engine` routing coverage and shrink the three hard-limit files, then rerun gates and retry the protected push.

## Validation
- `powershell -ExecutionPolicy Bypass -File scripts/worktree_guard.ps1 -Action Check`
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/validate_agent_contexts.py`
- `python scripts/validate_taste_invariants.py`
- `python scripts/run_lean_gate.py`
- `git push --force-with-lease origin codex/signals_engine`
