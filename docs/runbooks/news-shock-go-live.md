# News Shock Go-Live Runbook

## Scope
- Instruments: `BRN`, `GOLD`, `NG_US`.
- Objective:
  - catch root shocks and aftershocks (including multi-day continuation);
  - provide direction signal only when evidence quality is sufficient.

## Pipeline
1. Build/curate shock dataset from `shock_news_1h_annual_all.csv`.
2. Build high-impact label pack for Chat Pro.
3. Ingest Chat Pro labels into silver dataset.
4. Run readiness assessment and only then enable production signaling.

## Automated Daily Cycle
Use one command to build both task packs:
- `direction` pack: default `v2_clean` only (direction + causal).
- `causal` pack: default `broad,none` (causal-only to expand coverage).

```powershell
$env:PYTHONPATH='src'
python scripts/run_shock_label_cycle.py `
  --input-csv data/output/news_perf_365d_5m_opt/shock_news_1h_annual_all.csv `
  --output-dir data/output/shock_label_cycle_latest `
  --start-ts 2026-01-01T00:00:00Z `
  --min-abs-z 2.5 `
  --max-delay-min 60 `
  --direction-max-tasks 300 `
  --causal-max-tasks 900 `
  --direction-candidate-sources v2_clean `
  --causal-candidate-sources broad,none `
  --telegram-feed-path data/output/shock_alerts/live_shocks.csv `
  --telegram-feed-min-abs-z 2.0
```

If Chat Pro outputs are already available, add:
```powershell
  --direction-labels-jsonl data/output/shock_label_cycle_latest/direction/chat_labels.jsonl `
  --causal-labels-jsonl data/output/shock_label_cycle_latest/causal/chat_labels.jsonl `
  --ingest-min-confidence 0.6 `
  --run-readiness
```

Cycle output includes:
- `shock_label_cycle_manifest.json` (single source-of-truth for artifacts and counts),
- curated dataset and issue ledger,
- separate direction/causal packs and summaries,
- `telegram_live_shocks.csv` snapshot and rolling `data/output/shock_alerts/live_shocks.csv` feed for Telegram worker,
- optional silver ingest artifacts and readiness report.

## Windows Auto-Run (Task Scheduler)
Install daily auto-run task (default: every day at `09:10` local time):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_shock_label_cycle_task.ps1 `
  -Action Install `
  -StartTime 09:10
```

Check status:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_shock_label_cycle_task.ps1 -Action Status
```

Run immediately (manual trigger):
```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_shock_label_cycle_task.ps1 -Action Run
```

Remove task:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_shock_label_cycle_task.ps1 -Action Remove
```

Recommended live mode (`fresh + backfill` split):
- `fresh` task: repeats every 30 minutes, only recent window (`FreshLookbackHours=6`), updates Telegram feed.
- `backfill` task: once per day, broader historical coverage, does not overwrite Telegram feed.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_news_shock_live_plan.ps1 -Action Install
```

Check both tasks:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_news_shock_live_plan.ps1 -Action Status
```

Budget-aware defaults for `NewsAPI` daily limit `100`:
- realtime verification budget: `55`
- backfill budget: `35`
- emergency reserve: `10`

These are exposed as parameters in `manage_news_shock_live_plan.ps1`.

Task uses `scripts/start_shock_label_cycle.ps1` as launcher, which:
- sets `PYTHONPATH=src`,
- loads `scripts/moex-carry.local.ps1` if present,
- writes each run to `data/output/shock_label_cycle_auto/<UTC timestamp>/`,
- updates `data/output/shock_alerts/live_shocks.csv` (unless `-NoTelegramFeed` is set).
- supports rolling window mode via `-FreshLookbackHours` for frequent runs.

## Telegram Shock Alerts
- Ensure `telegram.enabled=true`, bot token and allowed users are configured.
- `configs/default.yaml` now sets `telegram.shock_alerts_enabled=true` and reads feed from `telegram.shock_feed_path`.
- Run worker:

```powershell
$env:PYTHONPATH='src'
python -m moex_carry.cli telegram_bot
```

## Commands
### 1) Label pack
```powershell
$env:PYTHONPATH='src'
python scripts/build_shock_label_pack.py `
  --input-csv data/output/news_perf_365d_5m_opt/shock_news_1h_annual_all.csv `
  --output-dir data/output/shock_label_pack_latest `
  --start-ts 2026-01-01T00:00:00Z `
  --min-abs-z 2.5 `
  --max-delay-min 60 `
  --candidate-source v2_clean
```

### 2) Ingest labels
```powershell
$env:PYTHONPATH='src'
python scripts/ingest_shock_labels.py `
  --tasks-jsonl data/output/shock_label_pack_latest/shock_label_pack_zge2p5.jsonl `
  --labels-jsonl data/output/shock_label_pack_latest/chat_pro_labels.jsonl `
  --output-dir data/output/shock_silver_latest `
  --min-confidence 0.6
```

### 3) Readiness report
```powershell
$env:PYTHONPATH='src'
python scripts/news_shock_readiness.py `
  --input-csv data/output/news_perf_365d_5m_opt/shock_news_1h_annual_all.csv `
  --output-dir data/output/news_shock_readiness_latest `
  --start-ts 2026-01-01T00:00:00Z `
  --max-delay-min 60 `
  --primary-z 2.5 `
  --aftershock-z 2.0 `
  --episode-window-min 10080 `
  --max-gap-min 2880
```

## Readiness Criteria (critical)
- `detector_primary_recall >= 0.70`
- `detector_aftershock_recall >= 0.75`
- `direction_v2_accuracy >= 0.58`
- `direction_v2_labeled_count >= 120`
- `direction_v2_coverage >= 0.07`
- `curation_critical_drop_share <= 0.05`
- `aftershock_1d_count >= 10`

If any critical check fails, production enablement is blocked.

## Production Mode Recommendation
- Detector layer: use current high-recall matching.
- Direction layer: use only `v2_clean` matched events.
- If direction evidence is absent, send shock alert without direction commitment.

## Artifacts
- `readiness_report.md` and `readiness_report.json`
- `readiness_checks.csv`, `readiness_metrics.csv`
- `readiness_curated_shocks.csv`, `readiness_curation_issues.csv`
- Episode capture artifacts: `shock_episode_events.csv`, `shock_mode_capture.csv`

## Known Failure Modes and Controls
- Extreme price artifacts from roll or bad ticks:
  - controlled by curation caps per symbol (`abs_move_pct`, `|z|`).
- Direction drift from broad noisy links:
  - direction quality measured separately on `v2_clean`.
- Short episode windows miss multi-day aftershocks:
  - readiness uses long topic profile (`7d window`, `2d max gap`).
