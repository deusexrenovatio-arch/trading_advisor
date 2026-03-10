# Agent Checks

## Loop (local hot path)
- `powershell -ExecutionPolicy Bypass -File scripts/worktree_guard.ps1 -Action Check`
- `python scripts/validate_task_request_contract.py`
- `python scripts/run_lean_gate.py`

## PR Closeout
- `python scripts/run_lean_gate.py`
- `python scripts/validate_quality_scorecards.py`
- Required checks from `docs/DEV_WORKFLOW.md`

## Nightly / Cold Hygiene
- docs gardening, governance dashboard, and scheduled deep checks.
- drift cleanup, archive hygiene, and long-running quality/perf probes.

## First-Time-Right Gate
- Use `docs/checklists/first-time-right-gate.md` before non-trivial implementation and pre-push.
- Report block is mandatory:
  1. Confirmed coverage.
  2. Missing or risky scenarios.
  3. Resource/time risks and controls.
  4. Highest-priority fixes or follow-ups.
