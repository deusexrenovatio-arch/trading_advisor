# News Live Runbook (3 Commodities)

## Scope
This runbook is limited to:
- `NG_US` (futures price symbol `NG=F`)
- `BRN` (futures price symbol `BZ=F`)
- `GOLD` (futures price symbol `GC=F`)

Goal:
- run near-live analytics for news and event impact,
- maintain daily silver-label growth,
- expose live gate decisions for trading flow.

## Prerequisites
- Worktree: `D:\wt-news-module`
- Config: `configs/default.yaml`
- Python module path set for local code:
```powershell
$env:PYTHONPATH = "D:\wt-news-module\src"
```
- Optional for incremental NewsAPI backfill:
```powershell
$env:NEWSAPI_API_KEY = "<key>"
```

## Live Modes

### 1) Shadow mode (recommended start)
Use predictions/analytics for monitoring only, without hard trading impact.

Start services in separate terminals:
```powershell
$env:PYTHONPATH="D:\wt-news-module\src"
python -m moex_carry.cli news_sync --config configs/default.yaml --interval-sec 300
```
```powershell
$env:PYTHONPATH="D:\wt-news-module\src"
python -m moex_carry.cli signals --config configs/default.yaml --max-pairs 200
```
```powershell
$env:PYTHONPATH="D:\wt-news-module\src"
python -m moex_carry.cli ui --config configs/default.yaml
```

Daily silver expansion for all three commodities:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_news_daily_silver_cycle_3c.ps1 `
  -Config configs/default.yaml `
  -Horizon 1h `
  -RunInference `
  -V2Selector hybrid `
  -MinModelConfidence 0.40 `
  -V2MinTargetConfidence 0.20 `
  -V2MinImpactBin 0 `
  -V2MinAbsZ 0.60 `
  -V2MinAbsAr 0.0002 `
  -AllowModelDisagreement `
  -AllowTargetMismatch `
  -AllowNoModelScores `
  -IncludeOverlap
```

Hourly reaction rebuild (market sanity):
```powershell
$env:PYTHONPATH="D:\wt-news-module\src"
python -m moex_carry.cli news_reactions --config configs/default.yaml --from-date 2026-03-01 --to-date 2026-03-02 --event-time-mode published
```

### 2) Active mode (after stability)
Enable only after shadow metrics stabilize for several days:
- silver growth is non-zero each day,
- no major leakage/coverage regressions in `news_qc` and reaction stats,
- live gate behavior is consistent with observed price moves.

## Recommended Scheduler Plan (Windows Task Scheduler)
- Every 5 minutes: `news_sync`
- Every 60 minutes: `news_reactions` for recent window
- Once per day (UTC early morning): `run_news_daily_silver_cycle_3c.ps1`
- Once per day: `news_qc` for rolling 365-day window

Example daily QC command:
```powershell
$env:PYTHONPATH="D:\wt-news-module\src"
python -m moex_carry.cli news_qc --config configs/default.yaml --from-date 2025-03-01 --to-date 2026-03-02 --commodities NG_US,BRN,GOLD
```

## Outputs to Watch
- Silver cycle summary/report:
  - `data/output/shock_silver_cycle_1h_relaxed/shock_silver_cycle_summary_1h.csv`
  - `data/output/shock_silver_cycle_1h_relaxed/shock_silver_cycle_report_1h.json`
  - `data/output/shock_silver_cycle_1h_relaxed/silver_high_conf_dataset_1h.jsonl`
- Live API:
  - `/api/v2/news/feed`
  - `/api/v2/signals/active`
  - `/api/v2/validation/*`

## Troubleshooting
- If CLI does not show `news_*` commands:
  - set `PYTHONPATH` to `D:\wt-news-module\src` before running CLI.
- If silver growth drops to zero:
  - temporarily relax daily thresholds in cycle command,
  - then tighten back after coverage recovers.
- If machine load is high:
  - reduce backfill windows and run inference in off-peak periods.
