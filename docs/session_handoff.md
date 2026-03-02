# Session Handoff
Updated: 2026-03-02 13:09 UTC

## Goal
- Align staged execution behavior with manual two-leg trading flow and rerun comparable base vs staged metrics.

## Current Delta
- Added sequential two-leg protocol fields (`sequential_entry_*`, `sequential_exit_*`) in config, contracts, replay settings, and resolver validation.
- Implemented staged leg-by-leg execution state machines in `src/moex_carry/signal_replay/minute_replay.py` and `src/moex_carry/pipeline.py`.
- Added second-leg timeout handling: `entry_second_leg_timeout_unwound` for entry and `exit_second_leg_timeout_forced` for exit.
- Published protocol details into `signal_metrics` in both unified and legacy signal pipelines.
- Updated Telegram signal message formatting to show staged entry/exit order, leg gap limits, and fallback penalties.
- Added tests for defaults and staged behavior in `tests/test_execution_replay.py`, `tests/test_backtest_defaults.py`, and `tests/test_telegram_worker.py`.
- Recomputed base vs staged comparison on 55 cached pairs (`2025-08-27..2026-02-23`) and saved reports under `data/reports/sequential_compare_*_20260302.*`.

## Blockers
- None.

## Next Step
- Tune staged leg gap / first-leg choice per pair cluster and rerun comparison with the same scenario frame.

## Validation
- `pytest tests/test_execution_replay.py tests/test_backtest_defaults.py tests/test_signal_replay_core.py tests/test_telegram_worker.py -q`
- `pytest tests/test_config_resolver.py tests/test_signal_api.py -q`
- `python scripts/intraday_period_pnl_eval.py --config configs/default.yaml --pairs "$(Get-Content data/reports/pairs_55_20260223.txt)" --from-date 2025-08-27 --till-date 2026-02-23 --signal-exec-lag-days 0 --scenario-specs "30,720,0.01,0.0125,0.015,0" --pair-workers 8 --preload-workers 8 --minute-chunk-days 21 --preload-cache-mode readonly --preload-cache-dir data/output/intraday_preload_cache_entry_exit_55 --out-pairs-csv data/reports/sequential_compare_base_pairs_20260302.csv --out-summary-csv data/reports/sequential_compare_base_summary_20260302.csv --out-summary-json data/reports/sequential_compare_base_summary_20260302.json`
- `python scripts/intraday_period_pnl_eval.py --config configs/default.sequential_staged.yaml --pairs "$(Get-Content data/reports/pairs_55_20260223.txt)" --from-date 2025-08-27 --till-date 2026-02-23 --signal-exec-lag-days 0 --scenario-specs "30,720,0.01,0.0125,0.015,0" --pair-workers 8 --preload-workers 8 --minute-chunk-days 21 --preload-cache-mode readonly --preload-cache-dir data/output/intraday_preload_cache_entry_exit_55 --out-pairs-csv data/reports/sequential_compare_staged_pairs_20260302.csv --out-summary-csv data/reports/sequential_compare_staged_summary_20260302.csv --out-summary-json data/reports/sequential_compare_staged_summary_20260302.json`
- `python scripts/run_lean_gate.py`
- `python scripts/validate_session_handoff.py`
