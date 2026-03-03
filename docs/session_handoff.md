# Session Handoff
Updated: 2026-03-03 12:30 UTC

## Goal
- Reach launch-ready shock-news workflow with deterministic data curation, scalable silver labeling loop, and explicit critical pass/fail readiness decision.

## Current Delta
- Added labeling cycle module/runner: `src/moex_carry/news_shock_automation.py`, `scripts/run_shock_label_cycle.py`.
- Added CLI command `shock_label_cycle` in `src/moex_carry/cli.py`.
- Added rolling Telegram shock feed export from cycle to `data/output/shock_alerts/live_shocks.csv` plus per-run snapshot artifact.
- Fixed feed construction bug by deriving `headline/url/event_id` from `selected_source + v2/broad` instead of missing `selected_*` fields.
- Extended cycle CLI and scheduler launchers with Telegram feed controls (`--telegram-feed-*` / `-TelegramFeed*`, `--no-telegram-feed` / `-NoTelegramFeed`).
- Enabled default Telegram shock broadcast in config: `configs/default.yaml` -> `telegram.shock_alerts_enabled=true`.
- Added regression test for feed export and fallback topic keys: `tests/test_news_shock_automation.py`.
- Updated runbook with Telegram worker flow and feed wiring: `docs/runbooks/news-shock-go-live.md`.

## Blockers
- No critical blockers for **2026 YTD launch scope**.
- Historical 365d backfill remains non-launch blocker (detector recall below threshold due older sparse matching period).

## Next Step
- Run `telegram_bot` in live loop and verify primary/aftershock delivery against latest `live_shocks.csv` cycles.

## Validation
- `powershell -ExecutionPolicy Bypass -File scripts/start_shock_label_cycle.ps1 -CheckOnly`
- `powershell -ExecutionPolicy Bypass -File scripts/manage_shock_label_cycle_task.ps1 -Action Install -DryRun`
- `python -m pytest tests/test_news_shock_automation.py tests/test_shock_alert_delivery.py tests/test_telegram_worker.py -q`
- `python -m ruff check src/moex_carry/news_shock_automation.py scripts/run_shock_label_cycle.py src/moex_carry/cli.py tests/test_news_shock_automation.py`
- `python scripts/run_lean_gate.py`
