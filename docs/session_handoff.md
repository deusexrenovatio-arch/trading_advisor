# Session Handoff
Updated: 2026-03-03 20:05 UTC

## Goal
- Reach launch-ready shock-news workflow with deterministic data curation, scalable silver labeling loop, and explicit critical pass/fail readiness decision.

## Current Delta
- Added automated labeling cycle module and runner: `src/moex_carry/news_shock_automation.py`, `scripts/run_shock_label_cycle.py`.
- Added CLI command `shock_label_cycle` in `src/moex_carry/cli.py`.
- Extended pack builder with `candidate_sources` filtering and `causal_only` mode in `src/moex_carry/news_shock_pipeline.py` and `scripts/build_shock_label_pack.py`.
- Added regression coverage for new modes and cycle artifacts: `tests/test_news_shock_pipeline.py`, `tests/test_news_shock_automation.py`.
- Updated runbook with one-command operation and dual-pack defaults: `docs/runbooks/news-shock-go-live.md`.
- Existing readiness artifacts remain valid for 2026 YTD launch scope: `data/output/news_shock_readiness_2026_ytd/readiness_report.md`.

## Blockers
- No critical blockers for **2026 YTD launch scope**.
- Historical 365d backfill remains non-launch blocker (detector recall below threshold due older sparse matching period).

## Next Step
- Start daily `shock_label_cycle` cron (direction `v2_clean`, causal `broad/none`), ingest Chat Pro outputs per pack, and monitor growth of high-confidence silver coverage.

## Validation
- `python -m pytest tests/test_news_shock_pipeline.py tests/test_news_shock_automation.py -q`
- `python -m ruff check src/moex_carry/news_shock_pipeline.py src/moex_carry/news_shock_automation.py scripts/build_shock_label_pack.py scripts/run_shock_label_cycle.py src/moex_carry/cli.py tests/test_news_shock_pipeline.py tests/test_news_shock_automation.py`
- `python -m pytest tests/test_news_shock_pipeline.py tests/test_news_shock_readiness.py tests/test_news_mode_compare.py tests/test_shock_episodes.py tests/test_shock_alert_delivery.py tests/test_telegram_worker.py -q`
- `python -m ruff check src/moex_carry/news_shock_pipeline.py src/moex_carry/news_shock_readiness.py scripts/build_shock_label_pack.py scripts/ingest_shock_labels.py scripts/news_shock_readiness.py src/moex_carry/cli.py tests/test_news_shock_pipeline.py tests/test_news_shock_readiness.py`
- `python scripts/news_shock_readiness.py --input-csv data/output/news_perf_365d_5m_opt/shock_news_1h_annual_all.csv --output-dir data/output/news_shock_readiness_2026_ytd --start-ts 2026-01-01T00:00:00Z --max-delay-min 60 --primary-z 2.5 --aftershock-z 2.0 --episode-window-min 10080 --max-gap-min 2880`
- `python scripts/run_lean_gate.py`
