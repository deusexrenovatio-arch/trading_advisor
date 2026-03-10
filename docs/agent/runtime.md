# Agent Runtime Routing

## Core Entrypoints
- `python scripts/measure_dev_loop.py`
- `python scripts/run_lean_gate.py`
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/validate_quality_scorecards.py`

## Worktree Safety
- Check: `powershell -ExecutionPolicy Bypass -File scripts/worktree_guard.ps1 -Action Check`
- Init: `powershell -ExecutionPolicy Bypass -File scripts/worktree_guard.ps1 -Action Init -WorktreePath "<path>" -Branch "<branch>" -ContextTtlHours 12`
- Show: `powershell -ExecutionPolicy Bypass -File scripts/worktree_guard.ps1 -Action Show`

## Telemetry and Recovery
- Task outcomes sync: `python scripts/sync_task_outcomes.py`
- Remediation guide: `docs/runbooks/governance-remediation.md`
- Process reports: `python scripts/process_improvement_report.py`

## Compatibility Rule
- During migration, keep wrapper entrypoints available for one transition cycle.
- Remove legacy aliases only after one successful nightly cycle plus one merged PR on new entrypoints.
