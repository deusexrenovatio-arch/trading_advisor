# Session Handoff
Updated: 2026-03-03 12:48 UTC

## Goal
- Reach launch-ready shock-news workflow with deterministic data curation, scalable silver labeling loop, and explicit critical pass/fail readiness decision.

## Current Delta
- Added rolling Telegram shock feed export from cycle to `data/output/shock_alerts/live_shocks.csv` plus snapshot artifact.
- Fixed feed candidate mapping (`selected_source + v2/broad`) so missing `selected_*` columns no longer break export.
- Added `FreshLookbackHours` mode in `scripts/start_shock_label_cycle.ps1` for frequent recent-window runs.
- `run_shock_label_cycle` now tolerates empty post-filter windows and does not overwrite live feed when curated is empty.
- Extended scheduler manager with repeat triggers (`ScheduleMode=Repeat`, `RepeatMinutes`, `RepeatDurationHours`) and lookback pass-through.
- Added dual-schedule orchestrator `scripts/manage_news_shock_live_plan.ps1` with NewsAPI budget split printout.
- Installed tasks: `MoexCarry-ShockLabelCycleFresh` (every 30m, lookback 6h) and `MoexCarry-ShockLabelCycleBackfill` (daily 03:40), removed legacy daily task.
- Added regression tests for feed export + empty-window no-overwrite and updated runbook with `fresh+backfill` model.

## Blockers
- No critical blockers in runtime scheduling.
- NewsAPI polling itself is external to this repo; enforced budget here is schedule policy and operational split.

## Next Step
- Verify one full day of `fresh` and `backfill` task runs (`LastTaskResult=0`) and compare delivered shock alerts vs expected high-impact windows.

## Validation
- `powershell -ExecutionPolicy Bypass -File scripts/start_shock_label_cycle.ps1 -CheckOnly`
- `powershell -ExecutionPolicy Bypass -File scripts/manage_shock_label_cycle_task.ps1 -Action Install -DryRun`
- `powershell -ExecutionPolicy Bypass -File scripts/manage_shock_label_cycle_task.ps1 -Action Install -TaskName MoexCarry-ShockLabelCycleFresh-Test -ScheduleMode Repeat -RepeatMinutes 30 -FreshLookbackHours 6 -DryRun`
- `powershell -ExecutionPolicy Bypass -File scripts/manage_news_shock_live_plan.ps1 -Action Install -DryRun`
- `powershell -ExecutionPolicy Bypass -File scripts/manage_news_shock_live_plan.ps1 -Action Install`
- `powershell -ExecutionPolicy Bypass -File scripts/manage_news_shock_live_plan.ps1 -Action Status`
- `powershell -ExecutionPolicy Bypass -File scripts/manage_news_shock_live_plan.ps1 -Action RunFresh`
- `powershell -ExecutionPolicy Bypass -File scripts/manage_news_shock_live_plan.ps1 -Action RunBackfill`
- `python -m pytest tests/test_news_shock_automation.py tests/test_shock_alert_delivery.py tests/test_telegram_worker.py -q`
- `python -m ruff check src/moex_carry/news_shock_automation.py scripts/run_shock_label_cycle.py src/moex_carry/cli.py tests/test_news_shock_automation.py`
- `python scripts/run_lean_gate.py`
