# Session Handoff
Updated: 2026-03-03 14:00 UTC

## Goal
- Run live commodity-news ingestion (GDELT + NewsAPI), score incoming news with model fallback, and feed runtime news gate.

## Current Delta
- Added `news_ingest` CLI command (`moex-carry news_ingest --news-config ... --mode live|backfill`).
- Implemented runtime ingestion with SQLite persistence, dedup, quota-aware NewsAPI usage, and rolling feed export.
- Added `NLI/FinBERT` primary scoring with auto GPU device selection and keyword fallback.
- Added bridge `load_news_gate_items` and wired `pipeline` to use live scored news instead of `news_items=[]`.
- Added scripts: `scripts/run_news_ingest_cycle.py`, `scripts/start_news_ingest_cycle.ps1`, `scripts/manage_news_ingest_tasks.ps1`.
- Updated config defaults for live gate fields and expanded `configs/news-livecheck-ng.yaml` for three commodities.
- Added live stability controls: GDELT/NewsAPI retry+backoff and NewsAPI per-commodity live interval throttling.
- Lean gate and quality scorecards pass after module split (`news_live_runtime`/`news_live_clients`/`news_live_scoring`).

## Blockers
- No code blockers.
- Runtime model quality still depends on available local model weights and GPU drivers; fallback is active by design.

## Next Step
- Keep 5-minute live scheduler active, monitor 24h commodity coverage and provider reliability, then tune profile queries for `BRN/GOLD` if coverage remains low.

## Validation
- `python -m pytest tests/test_news_live_runtime.py tests/test_news_filter.py -q`
- `python -m ruff check src/moex_carry/news_live_runtime.py src/moex_carry/news_live_clients.py src/moex_carry/news_live_scoring.py src/moex_carry/news_live_bridge.py src/moex_carry/cli.py src/moex_carry/pipeline.py scripts/run_news_ingest_cycle.py tests/test_news_live_runtime.py`
- `powershell -ExecutionPolicy Bypass -File scripts/start_news_ingest_cycle.ps1 -Mode live -CheckOnly`
- `powershell -ExecutionPolicy Bypass -File scripts/manage_news_ingest_tasks.ps1 -Action Install -DryRun`
- `python -m moex_carry.cli news_ingest --news-config configs/news-livecheck-ng.yaml --mode live`
- `python scripts/run_lean_gate.py`
- `python scripts/validate_quality_scorecards.py`
