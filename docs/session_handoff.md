# Session Handoff
Updated: 2026-03-04 09:35 UTC

## Goal
- Validate news-gate impact on morning-plan walk-forward using real commodity news data and keep causal execution.

## Current Delta
- Imported real data from `D:/New Project`: `data/news_livecheck_ng.db` and `data/output/news_live/live_news_signals.csv`.
- Confirmed DB coverage: `BRN`, `GOLD`, `NG_US` with >13k scored items total.
- Ran baseline and gate-on comparisons on real DB; default 180m lookback had near-zero overlap with setup timestamps.
- Performed lookback sweep; 4320m (3 days) reduced negative folds in dense scenario.
- Added risk-first reduce logic: on `reduce`, keep lowest `risk_ticks` setup(s) instead of first emitted setup.
- Applied the same reduce logic in both builder path and eval-cache fast-path.
- Updated tests for reduce behavior and preserved causal/news gate validation.

## Blockers
- No hard blockers.
- News overlap still depends on sparse setup timestamps; calibration should remain data-window specific.

## Next Step
- Move to next optimization block: cost/risk modulation with same protocol (integrate -> measure -> accept/reject).
- Keep `news_gate.lookback_minutes=4320` as experimental override, then re-validate on extended folds.

## Validation
- `python -m pytest tests/test_signal_engine_morning_plan.py tests/test_signal_engine_news_gate.py -q`
- `python scripts/run_morning_plan_walk_forward.py --config artifacts/research/tmp_disable_eligibility.yaml --instrument BRZ5 --instrument BRH6 --instrument NGU5 --instrument NGH6 --instrument GDZ5 --instrument GDH6 --instrument GDM6 --instrument-mode front_nearest --front-roll-avoid-expiry-days 3 --start-date 2025-08-01 --end-date 2026-02-20 --decision-times 10:30,12:00,14:00 --train-days 60 --test-days 20 --step-days 20 --search-algorithm RANDOM --search-space-profile intraday_goal_v2 --hpo-trials 8 --hpo-startup-trials 3 --hpo-seed 77 --cache-db data/cache/morning_plan_candles.sqlite --offline-only --enable-news-gate --news-gate-lookback-minutes 4320 --tick-size BRZ5=0.01 --tick-size BRH6=0.01 --tick-size NGU5=0.001 --tick-size NGH6=0.001 --tick-size GDZ5=0.1 --tick-size GDH6=0.1 --tick-size GDM6=0.1 --out-json artifacts/research/wf_news_realdb_dense_gate_lookback4320_riskpick_eval.json`
- `python scripts/run_lean_gate.py`
