# Task Note
Updated: 2026-03-11 06:20 UTC

## Goal
- Replace the mixed worktree/session orchestration with one canonical Python task-session contract and make `loop/pr` gates use cheap session-lock checks only.

## Task Request Contract
- Objective: implement the canonical session flow `task_session begin -> run_loop_gate -> run_pr_gate -> task_session end`, with one Python-only session lock, one task start, and no hidden routing/telemetry side effects inside session checks.
- In Scope: new `scripts/task_session.py`, Python session-lock model, refactor of `run_loop_gate.py` and `run_pr_gate.py` to use cheap session checks, removal of PowerShell-primary guard path and `run_lean_gate.py` wrapper flow, relocation of routing/task-start/task-end orchestration, hook/docs/test updates, and hot-path latency proof for the new contract.
- Out of Scope: unrelated domain/business logic, non-session governance refactors beyond what the new contract forces, and feature work outside the harness/runtime control path.
- Constraints: keep worktree/branch identity as a hard invariant, keep unknown-scope behavior fail-closed, remove duplicate ways to start/check a task, and do not hide task-start or routing inside ordinary loop checks.
- Done Evidence: `task_session begin/status/end` works as the only session lifecycle entrypoint, `run_loop_gate`/`run_pr_gate` pass with cheap session checks, PowerShell/legacy wrapper paths are removed from normal flow, targeted tests cover start-once/first-patch/session-mismatch/nightly hygiene, and updated timing baseline shows session-check hot-path cost and cold/warm matrix.
- Priority Rule: make the session contract simpler and more deterministic even if the refactor is broader; prefer one canonical path over layered compatibility.

## Current Delta
- `task_session begin/status/end` is now the canonical session lifecycle, and `begin` no longer syncs the task ledger on start.
- `run_loop_gate` and `run_pr_gate` use cheap session-lock checks, while hook/CI/nightly paths use explicit automation bypass instead of implicit PowerShell behavior.
- Legacy `worktree_guard` and `run_lean_gate` entrypoints are removed from active docs, hooks, validators, and tests; new session-contract regressions are in place.

## First-Time-Right Report
1. Confirmed coverage: the requested target flow explicitly defines begin, hot loop, PR gate, and end responsibilities, plus removal targets and latency criteria.
2. Missing or risky scenarios: stale session locks, branch/worktree mismatch after begin, repeated begin calls, and hidden task-start in gates can regress unless covered with dedicated tests.
3. Resource/time risks and chosen controls: refactor in one coherent pass, keep session payload minimal, and verify latency with a fresh timing capture instead of relying on inference.
4. Highest-priority fixes or follow-ups: Python-only session lock, explicit task lifecycle orchestration, then docs/hooks cleanup and hot-path timing proof.

## Repetition Control
- Max Same-Path Attempts: 2
- Stop Trigger: same validator or migration failure repeats after two attempts on unchanged path.
- Reset Action: stop patching current path, restore deterministic baseline checks, and switch to a new compatibility-first probe.
- New Search Space: (1) config-driven routing update, (2) wrapper/shim compatibility layer, (3) scoped validator arguments, (4) artifact migration script with dual-write.
- Next Probe: if the one-pass refactor still leaks orchestration into ordinary checks, stop adding shims and move the leaked responsibility into `task_session.py` plus a dedicated regression test before continuing.

## Task Outcome
- Outcome Status: completed
- Decision Quality: correct_after_replan
- Final Contexts: CTX-OPS
- Route Match: matched
- Primary Rework Cause: none
- Incident Signature: none
- Improvement Action: none
- Improvement Artifact: none
- Linked Plan ID: P1-AGENT-CONTEXT-V2-046

## Blockers
- No blocker.

## Next Step
- Run PR closeout on the new contract and finish the task session cleanly.

## Validation
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/task_session.py begin --request "<request>"`
- `python scripts/task_session.py status`
- `python scripts/run_loop_gate.py --from-git --git-ref HEAD`
- `python scripts/run_pr_gate.py --from-git --git-ref HEAD`
- `python scripts/task_session.py end`
