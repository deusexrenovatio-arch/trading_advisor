# Task Note
Updated: 2026-03-11 09:45 UTC

## Goal
- Close residual harness governance tails: stale plan gate path, archived contract inheritance, PR-only policy doc drift coverage, and optional news utility dependency guard.

## Task Request Contract
- Objective: eliminate the remaining fail-open paths in governance source-of-truth and validation coverage while keeping closeout flow deterministic.
- In Scope: active plan checks hygiene, `validate_plans` command-path validation, task-contract pointer safeguards, PR-only policy doc coverage updates, and `feedparser` optional dependency guard in standalone utility.
- Out of Scope: unrelated domain/runtime features, broad plan-archive migration, and non-governance refactors.
- Constraints: fail closed for active governance artifacts, preserve historical completed items, keep PR/loop scoped behavior deterministic, and provide regression tests for each fix.
- Done Evidence: updated validators reject stale active command refs, archived-note inheritance is blocked without scoped closeout evidence, PR-only policy validator covers release notes drift, and utility script reports install hint instead of raw `ModuleNotFoundError`.
- Priority Rule: prefer stronger correctness and policy integrity over minimal diff size.

## Current Delta
- Findings are narrowed to source-of-truth drift, policy coverage drift, and one optional dependency guard gap.

## First-Time-Right Report
1. Confirmed coverage: each reported tail has a direct code/doc touchpoint and corresponding validator/test seam.
2. Missing or risky scenarios: historical completed plans can contain legacy commands and must not block active governance validation.
3. Resource/time risks and chosen controls: apply scoped fail-closed checks and back each with focused regression tests.
4. Highest-priority fixes or follow-ups: block archived contract inheritance and stale active plan checks first, then close policy/docs and utility guardrails.

## Repetition Control
- Max Same-Path Attempts: 2
- Stop Trigger: repeated validator failure on unchanged path after two attempts.
- Reset Action: isolate the failing invariant with a dedicated minimal fixture and reapply the patch against that fixture.
- New Search Space: gate command scoping, handoff pointer semantics, policy-doc coverage matrix, optional import guard pattern.
- Next Probe: run focused governance tests plus direct validators on touched scripts.

## Task Outcome
- Outcome Status: completed
- Decision Quality: correct_first_time
- Final Contexts: CTX-OPS
- Route Match: matched
- Primary Rework Cause: none
- Incident Signature: none
- Improvement Action: none
- Improvement Artifact: none

## Blockers
- No blocker.

## Next Step
- Implement and validate all four tails, then close with terminal task outcome.

## Validation
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/validate_plans.py`
- `python scripts/validate_pr_only_policy.py`
