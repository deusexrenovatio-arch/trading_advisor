# Agent Checks

## Loop (local hot path)
- `python scripts/task_session.py status`
- `python scripts/validate_task_request_contract.py`
- `python scripts/run_loop_gate.py --from-git --git-ref HEAD`

## PR Closeout
- `python scripts/run_pr_gate.py --from-git --git-ref HEAD`
- `python scripts/task_session.py end`
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
