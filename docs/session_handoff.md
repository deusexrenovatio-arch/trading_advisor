# Session Handoff
Updated: 2026-03-04 09:10 UTC

## Goal
- Integrate live commodity news/fundamental feed into `signal_engine` morning-plan flow with causal gate semantics and no lookahead.

## Current Delta
- Added `signal_engine` news gate module with deterministic `allow/reduce/block` actions (`src/moex_carry/signal_engine/news/gate.py`).
- Wired gate into `MorningPlanBuilder` so generated setups are blocked/reduced by commodity news severity.
- Added `news_gate` section to `signal_engine.morning_plan` config model and defaults (`src/moex_carry/config.py`, `configs/default.yaml`).
- Extended walk-forward runner with news gate CLI overrides and report payload fields.
- Fixed architecture gap: applied news gate in eval-cache fast-path (`_compute_setups_cached`) so accelerated walk-forward matches builder behavior.
- Added tests for causal cutoff and unmapped handling (`tests/test_signal_engine_news_gate.py`).
- Added tests for builder block/reduce integration and config loading (`tests/test_signal_engine_morning_plan.py`, `tests/test_config_loading.py`).

## Blockers
- Local runtime DB `data/news_livecheck_ng.db` is empty (ingest cycle returned zero fetched rows), so real-feed smoke produced no gating events in selected period.

## Next Step
- Step 2 in sequence: integrate cost-aware net-gate refinements and run the same walk-forward comparison protocol.
- In parallel, fix news data availability (provider/query reliability) to validate step 1 on real events, not only synthetic gate smoke.

## Validation
- `python -m pytest tests/test_signal_engine_news_gate.py tests/test_signal_engine_morning_plan.py tests/test_config_loading.py -q`
- `python scripts/run_lean_gate.py`
- `python -m moex_carry.cli news_ingest --news-config configs/news-livecheck-ng.yaml --mode live`
- `python scripts/run_morning_plan_walk_forward.py --instrument BRZ5 --instrument BRH6 --instrument NGU5 --instrument NGH6 --instrument GDZ5 --instrument GDH6 --instrument GDM6 --instrument-mode front_nearest --front-roll-avoid-expiry-days 3 --start-date 2025-08-01 --end-date 2026-02-20 --decision-times 10:30,12:00,14:00 --train-days 60 --test-days 20 --step-days 20 --search-algorithm RANDOM --search-space-profile intraday_goal_v2 --hpo-trials 8 --hpo-startup-trials 3 --hpo-seed 77 --cache-db data/cache/morning_plan_candles.sqlite --offline-only --tick-size BRZ5=0.01 --tick-size BRH6=0.01 --tick-size NGU5=0.001 --tick-size NGH6=0.001 --tick-size GDZ5=0.1 --tick-size GDH6=0.1 --tick-size GDM6=0.1 --out-json artifacts/research/wf_news_gate_step1_front_baseline_eval.json`
- `python scripts/run_morning_plan_walk_forward.py --instrument BRZ5 --instrument BRH6 --instrument NGU5 --instrument NGH6 --instrument GDZ5 --instrument GDH6 --instrument GDM6 --instrument-mode front_nearest --front-roll-avoid-expiry-days 3 --start-date 2025-08-01 --end-date 2026-02-20 --decision-times 10:30,12:00,14:00 --train-days 60 --test-days 20 --step-days 20 --search-algorithm RANDOM --search-space-profile intraday_goal_v2 --hpo-trials 8 --hpo-startup-trials 3 --hpo-seed 77 --cache-db data/cache/morning_plan_candles.sqlite --offline-only --enable-news-gate --tick-size BRZ5=0.01 --tick-size BRH6=0.01 --tick-size NGU5=0.001 --tick-size NGH6=0.001 --tick-size GDZ5=0.1 --tick-size GDH6=0.1 --tick-size GDM6=0.1 --out-json artifacts/research/wf_news_gate_step1_front_news_eval.json`
- `python scripts/run_morning_plan_walk_forward.py --instrument BRZ5 --instrument BRH6 --instrument NGU5 --instrument NGH6 --instrument GDZ5 --instrument GDH6 --instrument GDM6 --instrument-mode front_nearest --front-roll-avoid-expiry-days 3 --start-date 2025-08-01 --end-date 2026-02-20 --decision-times 10:30,12:00,14:00 --train-days 60 --test-days 20 --step-days 20 --search-algorithm RANDOM --search-space-profile intraday_goal_v2 --hpo-trials 8 --hpo-startup-trials 3 --hpo-seed 77 --cache-db data/cache/morning_plan_candles.sqlite --offline-only --enable-news-gate --news-gate-db-url sqlite:///./artifacts/research/news_gate_synth_smoke.db --tick-size BRZ5=0.01 --tick-size BRH6=0.01 --tick-size NGU5=0.001 --tick-size NGH6=0.001 --tick-size GDZ5=0.1 --tick-size GDH6=0.1 --tick-size GDM6=0.1 --out-json artifacts/research/wf_news_gate_step1_front_news_synth_eval.json`
