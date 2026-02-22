# Session Handoff
Updated: 2026-02-22 00:00 UTC

## Goal
- Keep signal troubleshooting deterministic across worktrees, runtime processes, and data layers.

## Current Delta
- Added `docs/runbooks/signal-agent-continuity.md` with repeated-issue RCA and operational contracts.
- Documented canonical source order for signal verification: worktree -> process source -> unified projection -> root aliases -> DB.
- Explicitly separated replay sample metrics (`trades_closed` and related) from real executions (`signal_executions`).
- Added mandatory signal verification checklist to prevent stale-file and wrong-runtime conclusions.
- Updated `memory/agent_memory.yaml` with durable decision, incident, and pattern for signal continuity.

## Blockers
- None.

## Next Step
- Apply the runbook in the next signal change cycle and verify no cross-worktree source drift.
- Keep `## Current Delta` within eight bullets and avoid long transcript copies.

## Validation
- Run `python scripts/validate_session_handoff.py` for handoff contract checks.
- Run `python scripts/run_lean_gate.py` before and after meaningful patches.
