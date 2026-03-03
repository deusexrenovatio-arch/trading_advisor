# Session Handoff
Updated: 2026-03-03 19:15 UTC

## Goal
- Reach launch-ready shock-news workflow with deterministic data curation, scalable silver labeling loop, and explicit critical pass/fail readiness decision.

## Current Delta
- Implemented shock data curation with per-symbol outlier caps and issue ledger:
  `src/moex_carry/news_shock_pipeline.py`.
- Implemented Chat Pro labeling loop:
  label-pack builder + JSONL writer + label ingest with confidence gating:
  `src/moex_carry/news_shock_pipeline.py`,
  `scripts/build_shock_label_pack.py`,
  `scripts/ingest_shock_labels.py`.
- Implemented launch-readiness engine with critical checks and artifacts:
  `src/moex_carry/news_shock_readiness.py`,
  `scripts/news_shock_readiness.py`.
- Added CLI commands for end-to-end operation:
  `shock_label_pack`, `shock_labels_ingest`, `news_shock_readiness` in `src/moex_carry/cli.py`.
- Added runbook:
  `docs/runbooks/news-shock-go-live.md`.
- Produced production-style readiness artifacts:
  `data/output/news_shock_readiness_2026_ytd/readiness_report.md` (overall ready = YES),
  `data/output/news_shock_readiness_365d/readiness_report.md` (historical window fail due low detector recall).
- Fixed operational packaging drift by reinstalling editable package in active worktree before CLI smoke run.

## Blockers
- No critical blockers for **2026 YTD launch scope**.
- Historical 365d backfill remains non-launch blocker (detector recall below threshold due older sparse matching period).

## Next Step
- Run Telegram worker in shadow with live shock feed and monitor 1-2 weeks using readiness checks daily (rolling window), then switch alerts to active mode.

## Validation
- `python -m pytest tests/test_news_shock_pipeline.py tests/test_news_shock_readiness.py tests/test_news_mode_compare.py tests/test_shock_episodes.py tests/test_shock_alert_delivery.py tests/test_telegram_worker.py -q`
- `python -m ruff check src/moex_carry/news_shock_pipeline.py src/moex_carry/news_shock_readiness.py scripts/build_shock_label_pack.py scripts/ingest_shock_labels.py scripts/news_shock_readiness.py src/moex_carry/cli.py tests/test_news_shock_pipeline.py tests/test_news_shock_readiness.py`
- `python scripts/news_shock_readiness.py --input-csv data/output/news_perf_365d_5m_opt/shock_news_1h_annual_all.csv --output-dir data/output/news_shock_readiness_2026_ytd --start-ts 2026-01-01T00:00:00Z --max-delay-min 60 --primary-z 2.5 --aftershock-z 2.0 --episode-window-min 10080 --max-gap-min 2880`
- `python scripts/run_lean_gate.py`
