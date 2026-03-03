# Session Handoff
Updated: 2026-03-03 06:06 UTC

## Goal
- Stabilize `main` daily `self-heal` workflow by removing false-failure path in auto-PR step.

## Current Delta
- Reviewed scheduled `self-heal` failures on `main` from 2026-02-22 through 2026-03-03 via `gh run`.
- Confirmed `scripts/self_heal.py` and lean gate pass; failure happens in `peter-evans/create-pull-request`.
- Root cause: generated `self-heal-report.json` was treated as drift, then PR creation failed due repository policy forbidding Actions PR creation.
- Updated `.github/workflows/self-heal.yml` to detect drift only for governed files and run PR step only when those files changed.
- Limited PR commit scope with `add-paths` to `docs/architecture/architecture-map-data.js` and `plans/PLANS.yaml`.

## Blockers
- None.

## Next Step
- Trigger `self-heal` manually once and verify green run when no drift files changed.

## Validation
- `python scripts/run_lean_gate.py`
- `python scripts/validate_session_handoff.py`
