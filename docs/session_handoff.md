# Session Handoff
Updated: 2026-03-02 14:27 UTC

## Goal
- Improve morning-plan profitability robustness on broad commodity futures universe using strictly causal walk-forward.

## Current Delta
- Implemented robust train selection in `scripts/run_morning_plan_walk_forward.py` with objective `robust_median_mad` (`median expectancy - k * MAD` across instruments).
- Added pre-selection threshold `min_train_trades` with new default `80`.
- Added coverage thresholds: `min_train_instruments_with_trades=8` and `min_trades_per_instrument=3`.
- Added CLI controls for robust selection: `--selection-objective`, `--min-train-instruments-with-trades`, `--min-trades-per-instrument`, `--robust-mad-penalty`.
- Extended summaries with instrument-level attribution: `overall_test_summary.by_instrument`.
- Added per-fold `train_selection_metrics` to expose robust score and coverage used for selected params.
- Added tests in `tests/test_morning_plan_walk_forward.py` for instrument attribution and robust median/MAD scoring.

## Blockers
- None.

## Next Step
- Implement Priority #2: cost-aware pre-trade net-gate in setup generation (`min_reward_net_ticks`, `min_rr_net`, `min_reward_gross_ticks`) and validate on existing offline cache reports.

## Validation
- `PYTHONPATH=src pytest tests/test_morning_plan_walk_forward.py -q`
- `python scripts/run_lean_gate.py`
