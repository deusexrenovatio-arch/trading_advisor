# Session Handoff
Updated: 2026-02-20 00:00 UTC

## Goal
- Keep team communication compact while preserving deterministic delivery checks.

## Current Delta
- Added a machine-checked context budget validator for session handoff hygiene.
- Added workflow documentation that standardizes short delta-first updates.
- Wired the new validator into the default lean gate.

## Blockers
- None.

## Next Step
- Update this file at the end of each meaningful patch or stream handover.
- Keep `## Current Delta` within eight bullets and avoid long transcript copies.

## Validation
- Run `python scripts/validate_session_handoff.py` for handoff contract checks.
- Run `python scripts/run_lean_gate.py` before and after meaningful patches.
