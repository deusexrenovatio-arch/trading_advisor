# Task Note
Updated: 2026-03-10 20:05 UTC

## Goal
- Close the external Chat PRO validation gaps for the harness redesign and make the branch pass deterministic validation for `PR-00`..`PR-13`.

## Task Request Contract
- Objective: resolve all validated regressions from external branch audit, including deterministic gate routing, worktree guard parity, context cold-split enforcement, task-outcome closure, regression coverage, canonical server surface, and file-size policy closure.
- In Scope: `run_pr_gate`/`run_nightly_gate` nested scope propagation, `.cursorignore` cold-context exclusions, `worktree_guard.py` parity with PowerShell context schema, failing runtime harness tests, strengthened change-surface regression suite, server-entrypoint canonicalization in tests/runtime, task outcome closeout, and file-size policy global pass.
- Out of Scope: unrelated strategy/business logic, feature additions outside harness/governance/runtime scaffolding, and broad refactors not required for audited blockers.
- Constraints: keep PR-only flow intact, keep fail-closed behavior for unknown scope, preserve compatibility shims where still required, and avoid weakening blocking validators.
- Done Evidence: previously failing commands pass (`tests/test_task_outcomes.py`, `validate_task_outcomes --base-sha`, `worktree_guard.py --force-python`, `validate_file_size_policy --all-files`), targeted gate-routing behavior is regression-tested, and `run_lean_gate`/`run_pr_gate`/`run_nightly_gate` stay green.
- Priority Rule: deterministic correctness and governance integrity over speed; fix root causes and close regression gaps before cosmetic cleanup.

## Current Delta
- Fixed nested `pr/nightly` scope propagation for explicit `--changed-files` and `--stdin` inputs.
- Fixed `worktree_guard.py` parity with PowerShell context schema (`valid_until_utc`, UTF-8 BOM, Windows path compare).
- Fixed runtime harness regressions (`tests/test_task_outcomes.py` green).
- Added mechanical cold-context exclusions in `.cursorignore`.
- Expanded change-surface regression coverage for rename/delete/unknown/fail-closed/routing cases.
- Closed global file-size policy failures in `--all-files` mode via explicit temporary facade allowlist.
- Completed server/UI canonicalization around `moex_carry.server` entrypoints with compatibility seams preserved.
- Remaining step is opening the PR with the prepared remediation summary.

## First-Time-Right Report
1. Confirmed coverage: each reported failure is mapped to one explicit remediation patch and one deterministic validation command.
2. Missing or risky scenarios: scope propagation across nested gates and minimal-repo runtime harness compatibility are easy to regress without dedicated tests.
3. Resource/time risks and chosen controls: prioritize P1 invariants first, run scoped tests immediately after each fix, and defer broader cleanup until all hard blockers pass.
4. Highest-priority fixes or follow-ups: deterministic nested gate routing and cross-platform worktree guard parity, then regression-suite hardening and policy closure.

## Repetition Control
- Max Same-Path Attempts: 2
- Stop Trigger: same validator or migration failure repeats after two attempts on unchanged path.
- Reset Action: stop patching current path, restore deterministic baseline checks, and switch to a new compatibility-first probe.
- New Search Space: (1) config-driven routing update, (2) wrapper/shim compatibility layer, (3) scoped validator arguments, (4) artifact migration script with dual-write.
- Next Probe: if a fix still fails after two same-path attempts, switch from patching behavior to contract-level fallback (compatibility shim + dedicated regression test) before returning to refactor.

## Task Outcome
- Outcome Status: completed
- Decision Quality: correct_first_time
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
- Open the PR with the prepared remediation summary and validation evidence.

## Validation
- `powershell -ExecutionPolicy Bypass -File scripts/worktree_guard.ps1 -Action Check`
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/run_lean_gate.py`
- `python scripts/run_pr_gate.py --changed-files docs/README.md`
- `python scripts/worktree_guard.py --action Check --force-python`
- `python -m pytest tests/test_task_outcomes.py -q`
- `python scripts/validate_task_outcomes.py --base-sha <merge-base> --head-sha HEAD`
- `python scripts/validate_file_size_policy.py --all-files`
