# Session Handoff
Updated: 2026-02-22 09:47 UTC

## Goal
- Keep signal troubleshooting deterministic across worktrees, runtime processes, and data layers.

## Current Delta
- Added `docs/runbooks/signal-agent-continuity.md` with repeated-issue RCA and operational contracts.
- Documented canonical source order for signal verification: worktree -> process source -> unified projection -> root aliases -> DB.
- Explicitly separated replay sample metrics (`trades_closed` and related) from real executions (`signal_executions`).
- Added mandatory signal verification checklist to prevent stale-file and wrong-runtime conclusions.
- Added quality-scorecards trajectory dimension with blocking checks for two API v2 critical paths.
- Added quality-scorecards context-budget dimension using `scripts/validate_session_handoff.py`.
- Added API v2 request-id propagation into response headers and payload-size guard (`ui.max_api_payload_bytes`) returning `413 payload_too_large`.
- Added regression tests for request-id propagation/payload-size rejection and stabilized Playwright history fixture dates for the default 7-day window.

## Blockers
- None.

## Next Step
- Keep trajectory checks aligned with the highest-risk user flows as new endpoints are added.
- Apply the runbook in the next signal change cycle and verify no cross-worktree source drift.
- Keep `## Current Delta` within eight bullets and avoid long transcript copies.

## Validation
- Run `python scripts/validate_session_handoff.py` for handoff contract checks.
- Run `python scripts/run_lean_gate.py` before and after meaningful patches.
