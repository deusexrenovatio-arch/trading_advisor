# Session Handoff
Updated: 2026-03-03 00:29 UTC

## Goal
- Implement the new main TZ as a futures-first morning planning pipeline (`D1/H1/M5 -> regime -> levels -> execution -> setups`) inside existing `signal_engine` architecture.

## Current Delta
- Added SQLite candle cache mode to `scripts/run_morning_plan_walk_forward.py` for offline-first reruns.
- Added cache flags: `--cache-db`, `--offline-only`, `--refresh-cache`, `--prefetch-only`, `--no-cache`.
- `prefetch-only` now fills cache once; further walk-forward runs can be executed fully offline.
- Added cache behavior tests in `tests/test_morning_plan_walk_forward.py` (cache hit and offline cache miss).
- Verified flow on commodity futures (`BRH6`, `NGH6`, `GDH6`): prefetch fetches ISS once, offline rerun works without network.
- Existing causal fold logic and comparison metrics remain unchanged.

## Blockers
- None.

## Next Step
- Expand universe to next expiries and run longer offline folds with stricter `min_train_trades` threshold.

## Validation
- `PYTHONPATH=src pytest tests/test_morning_plan_walk_forward.py -q`
- `PYTHONPATH=src python scripts/run_morning_plan_walk_forward.py --instrument BRH6 --instrument NGH6 --instrument GDH6 --start-date 2026-02-10 --end-date 2026-02-20 --decision-time 12:00 --train-days 10 --test-days 5 --step-days 5 --min-train-trades 1 --prefetch-only --out-json data/output/research/morning_prefetch_20260210_20260220.json`
- `PYTHONPATH=src python scripts/run_morning_plan_walk_forward.py --instrument BRH6 --instrument NGH6 --instrument GDH6 --start-date 2026-02-10 --end-date 2026-02-20 --decision-time 12:00 --train-days 10 --test-days 5 --step-days 5 --min-train-trades 1 --offline-only --out-json data/output/research/morning_offline_wf_20260210_20260220.json`
- `python scripts/run_lean_gate.py`
