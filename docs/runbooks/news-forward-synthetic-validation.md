# News Forward Synthetic Validation (No-Lookahead)

## Goal
- Prove pre-launch that root/aftershock detector behavior is stable on known historical shocks **without** using post-move information in the live decision stage.

## Core Principle
- `Live signal` uses only information available at event timestamp (`t0`).
- `1H/1D move` is used only as offline evaluation target.
- Thresholds are selected on **past windows only** and frozen for each next test window.

## Anti-Leakage Rules
1. Drop rows with `leakage_postmove=1` when present.
2. Candidate-event delays must satisfy `0 <= delay <= max_delay`.
3. No global optimization on full history: use rolling walk-forward.
4. For each test window, choose profile (`broad_min_relevance`, `v2_min_relevance`) on calibration slice that ends before window start.

## Script
- [scripts/news_forward_synthetic.py](C:/Users/Admin/.codex/worktrees/fdcb/New Project/scripts/news_forward_synthetic.py)

## Known Events Coverage (Walk-Forward)
Use this when the target is "how many known root events are caught" (not row-level shock coverage).

- Script:
  - [scripts/news_known_events_walkforward.py](C:/Users/Admin/.codex/worktrees/fdcb/New Project/scripts/news_known_events_walkforward.py)
- Input:
  - `docs/research/news_golden_events_gold.csv` (`root_hit=true` = known event rows)
- No-lookahead rule:
  - threshold profile (`min_fundamental`, `min_confidence`) is selected on calibration slice only.
- Modes:
  - `discovery`: high-recall search mode for known-event coverage backtests.
  - `publish`: stricter mode for Telegram/live publication filtering.
  - default rumor handling: `discovery` allows rumor candidates; `publish` blocks rumor candidates.

Example:
```powershell
$env:PYTHONPATH='src'
python scripts/news_known_events_walkforward.py `
  --known-events-csv docs/research/news_golden_events_gold.csv `
  --output-dir data/output/news_known_events_walkforward_latest `
  --causal-profile discovery `
  --warmup-days 120 `
  --test-window-days 14 `
  --step-days 14 `
  --min-calibration-rows 60 `
  --min-test-known-rows 6 `
  --grid-min-fundamental 0.2,0.3,0.4,0.5,0.6 `
  --grid-min-confidence 0.2,0.3,0.4,0.5,0.6 `
  --min-calibration-precision 0.40 `
  --gate-known-row-recall 0.90 `
  --gate-known-event-coverage 0.90 `
  --gate-precision 0.40
```

Artifacts:
- `known_events_walkforward_windows.csv`
- `known_events_walkforward_summary.json`
- `known_events_walkforward_report.md`
- `known_events_walkforward_found.csv`
- `known_events_walkforward_missed.csv`

Latest reference run (`discovery`, 2026-03-05):
- `avg_known_row_recall = 0.971`
- `avg_known_event_coverage = 0.976`
- `avg_precision = 0.608`

## Example Run
```powershell
$env:PYTHONPATH='src'
python scripts/news_forward_synthetic.py `
  --input-csv data/output/shock_backfill_expanded_90d.csv `
  --output-dir data/output/news_forward_synth_latest `
  --warmup-days 45 `
  --test-window-days 7 `
  --step-days 7 `
  --min-calibration-rows 300 `
  --min-test-rows 40 `
  --max-delay-min 60 `
  --sweep-broad-grid 0.2,0.4,0.6,0.8,1.0 `
  --sweep-v2-grid 0.0,0.1,0.2,0.3,0.4,0.5 `
  --sweep-min-coverage 0.10 `
  --primary-z 2.5 `
  --aftershock-z 2.0 `
  --episode-window-min 10080 `
  --max-gap-min 2880 `
  --gate-primary-recall 0.90 `
  --gate-aftershock-recall 0.90 `
  --gate-precision 0.25
```

## Artifacts
- `forward_synthetic_windows.csv`: per-window metrics and pass/fail flags.
- `forward_synthetic_summary.json`: aggregate metrics and gate config.
- `forward_synthetic_report.md`: quick human-readable summary.
- `forward_synthetic_curation_issues.csv`: dropped-row reasons.
- `forward_synthetic_curation_summary.csv`: per-symbol curation stats.

## Promotion Gates (recommended)
1. `window_pass_rate >= 0.70`
2. `avg_primary_recall_episode >= 0.90`
3. `avg_aftershock_recall_episode >= 0.90`
4. `avg_news_to_shock_precision >= 0.25`

If any gate fails, do not enable forward production routing; recalibrate only on past data and rerun.
