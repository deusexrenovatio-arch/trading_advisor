# Task Note
Updated: 2026-03-11 13:12 UTC

## Goal
- Close all PR review findings for lean harness: correct surface routing, slim hot/pr paths, symmetric contracts escalation, isolated runtime, tighter context budget, and measured speed-up evidence.

## Task Request Contract
- Objective: fully remediate the six review findings so local loop/PR behavior is accurate, deterministic, and faster without correctness regressions.
- In Scope: change-surface mapping + classifier fallback, loop/pr command profile rebalance, contracts-to-ui loop escalation, runtime bootstrap port isolation, hot-context source tightening, and timing evidence artifacts.
- Out of Scope: unrelated product features, broad domain refactors, and governance policy redesign outside the reported findings.
- Constraints: preserve fail-closed behavior for unknown non-product files, keep task/session contracts valid, and add regression tests for each corrected behavior.
- Done Evidence: targeted tests pass for mapping/escalation/runtime, loop/pr gates run with updated profiles, and timing artifacts show before/after budgets for scoped profiles.
- Priority Rule: prioritize correctness and deterministic routing over minimal diff size; only keep checks in hot paths that directly protect changed surface behavior.

## Current Delta
- Review points were reproduced in code/config and confirmed as valid.
- Blocker is rooted in unmatched-to-governance behavior with incomplete core mapping coverage.
- Loop and PR profiles still include cold-governance checks that should be moved out of fast paths.
- Runtime and context split are improved but still short of worktree-isolated and tight hot-context targets.

## First-Time-Right Report
1. Confirmed coverage: each review finding maps to a concrete config/script/doc artifact with direct regression-test seams.
2. Missing or risky scenarios: broad fallback changes can over-route checks; risk is controlled by focused tests on docs-only, contracts, core, and unknown paths.
3. Resource/time risks and chosen controls: speed measurements can be noisy, so baseline and post-change runs will use the same profile matrix and iteration count.
4. Highest-priority fixes or follow-ups: fix surface misclassification blocker first, then fast-path slimming and contracts escalation symmetry, then runtime/context and speed evidence.

## Repetition Control
- Max Same-Path Attempts: 2
- Stop Trigger: same finding persists after two edits on the same script/config path.
- Reset Action: freeze patching, build a minimal failing fixture/test first, then patch to green against that fixture.
- New Search Space: classifier fallback heuristics, profile-level command relocation, runtime coordinate derivation, and context-budget doc routing.
- Next Probe: run focused tests for `compute_change_surface`, `run_loop_gate`, and runtime bootstrap before full loop/pr gates.

## Task Outcome
- Outcome Status: in_progress
- Decision Quality: pending
- Final Contexts: pending
- Route Match: pending
- Primary Rework Cause: none
- Incident Signature: none
- Improvement Action: pending
- Improvement Artifact: pending

## Blockers
- No blocker.

## Next Step
- Implement mapping/classifier and loop/pr profile fixes with regression tests, then validate runtime/context updates and timing evidence.

## Validation
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/run_loop_gate.py --from-git --git-ref HEAD`
