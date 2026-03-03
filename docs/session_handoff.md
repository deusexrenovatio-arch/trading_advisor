# Session Handoff
Updated: 2026-03-03 04:47 UTC

## Goal
- Shift morning-plan to intraday set-and-wait profile: several entries per week, potential target from 0.5%, mandatory same-day MOEX exit.

## Current Delta
- Added strategy-level target filter `setups.min_target_return_pct` (default `0.5`) in setup generation.
- Added objective/goal docs for morning intraday profile in `docs/research/evaluation-policy.md` and `docs/hpo-howto.md`.
- Extended walk-forward runner with `--search-algorithm GRID|RANDOM|TPE`.
- Added TPE search space profile `intraday_goal_v1` for non-bruteforce HPO.
- Added goal-aware train selection score with weekly trade-frequency penalty band (`min..max trades/week`).
- Added CLI goal controls: `--goal-min-target-return-pct`, `--goal-min-trades-per-week`, `--goal-max-trades-per-week`.
- Added tests for search-space resolution, goal score behavior, and target-return gate.
- First TPE starts are reproducible but unstable: trial12 v1 `net +2`, trial12 v2 `net -116`, trial24 `net -484`.

## Blockers
- None.

## Next Step
- Calibrate objective to percent-normalized returns and tighten search bounds around conservative risk to stabilize TPE before expanding trial budget.

## Validation
- `PYTHONPATH=src pytest tests/test_morning_plan_walk_forward.py tests/test_signal_engine_setups.py tests/test_config_loading.py tests/test_signal_engine_morning_plan.py -q`
- `PYTHONPATH=src python scripts/run_morning_plan_walk_forward.py --search-algorithm TPE --search-space-profile intraday_goal_v1 --hpo-trials 12 --hpo-startup-trials 4 --goal-min-target-return-pct 0.5 --goal-min-trades-per-week 2 --goal-max-trades-per-week 12 --selection-objective robust_median_mad --tuning-profile cost_aware_v2 --cost-model-profile fixed_v1 --offline-only ... --out-json data/output/research/morning_offline_wf_2026ytd_goods32_tpe_intraday_goal_v1_trial12_v2.json`
- `python scripts/run_lean_gate.py`
