# Agent Runtime Routing

## Core Entrypoints
- `python scripts/measure_dev_loop.py`
- `python scripts/task_session.py begin --request "<request>"`
- `python scripts/task_session.py status`
- `python scripts/task_session.py end`
- `python scripts/run_loop_gate.py --from-git --git-ref HEAD`
- `python scripts/run_pr_gate.py --from-git --git-ref HEAD`
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/validate_quality_scorecards.py`

## Session Safety
- Begin: `python scripts/task_session.py begin --request "<request>"`
- Check: `python scripts/task_session.py status`
- End: `python scripts/task_session.py end`

## Telemetry and Recovery
- Task closeout sync: `python scripts/task_session.py end`
- Remediation guide: `docs/runbooks/governance-remediation.md`
- Process reports: `python scripts/process_improvement_report.py`

## Contract Rule
- Session start, hot loop, PR gate, and closeout use one Python contract.
- Do not reintroduce wrapper entrypoints or PowerShell-specific guard paths.
