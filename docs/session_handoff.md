# Session Handoff
Updated: 2026-03-04 15:13 UTC

## Goal
- Remove popup console windows when worker/background processes are started locally.

## Task Request Contract
- Objective: audit current worker launchers and enforce hidden/headless process start so new console windows do not interrupt work.
- In Scope: PowerShell launch scripts and scheduled-task argument templates used to start backend, Telegram worker, frontend, news ingest, and shock label cycle workers.
- Out of Scope: worker business logic, API behavior, and trading/news processing algorithms.
- Constraints: keep existing singleton checks and log redirection behavior; preserve task names/schedules.
- Done Evidence: `python scripts/validate_task_request_contract.py`, `python scripts/run_lean_gate.py`, and launcher search output showing hidden-window flags on worker paths.
- Priority Rule: prioritize zero popup windows while preserving current automation behavior.

## Current Delta
- Identified popup source: `scripts/start_all_background.ps1` starts backend/worker/frontend via `Start-Process` without hidden window flags.
- Confirmed active worker wrappers are running under `powershell.exe` parent processes for backend and Telegram worker.
- Scoped scheduled-task launcher paths for autostart, news ingest, and shock label cycle workers.
- Updated installed `MoexCarry-NewsIngest*` and `MoexCarry-ShockLabelCycle*` tasks to include `-WindowStyle Hidden` in action arguments.
- Relaunched backend and Telegram worker in hidden mode; frontend launch still depends on local `vite` availability.

## First-Time-Right Report
1. Confirmed coverage: manual background launcher and scheduled-task templates for all recurring workers are included.
2. Missing or risky scenarios: already installed scheduled tasks keep old arguments until they are reinstalled/updated.
3. Resource/time risks and chosen controls: low-risk script-only changes with pre/post lean gate enforcement.
4. Highest-priority fixes or follow-ups: patch all worker launch paths to hidden window mode and provide update step for existing scheduled tasks.

## Repetition Control
- Max Same-Path Attempts: 2
- Stop Trigger: two launcher-edit attempts fail to suppress popup windows during real run.
- Reset Action: stop patching, snapshot effective scheduled-task actions/process tree, then switch to one-worker minimal repro.
- New Search Space: (1) `Start-Process` flags and host executable choice, (2) ScheduledTask action arguments/logon mode, (3) direct executable launch without shell wrapper.
- Next Probe: run one clean launch per worker path and verify no visible console window appears.

## Blockers
- No blockers.

## Next Step
- Apply hidden-window changes to worker launchers, then rerun task-contract validation and lean gate.

## Validation
- `python scripts/validate_task_request_contract.py`
- `python scripts/run_lean_gate.py`
