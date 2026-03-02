# Session Handoff
Updated: 2026-03-02 14:56 UTC

## Goal
- Improve morning-plan profitability robustness on broad commodity futures universe using strictly causal walk-forward.

## Current Delta
- Added robust train selection and coverage thresholds in walk-forward runner.
- Added setup-level cost-aware net gate and ATR-vs-cost eligibility filter.
- Added tuning profile presets in runner: `baseline_v1` and `cost_aware_v2`.
- `cost_aware_v2` tunes net controls: `min_rr_net`, `min_reward_net_ticks`, `max_risk_atr_mult`, `sl_atr_mult`, `buffer_atr_mult`.
- Added tests for tuning profile resolution and setup gate/eligibility behavior.
- Offline causal WF with `cost_aware_v2` on 32 instruments improved to near breakeven: `net_ticks_sum -32`, `expectancy -1.45`.
- 6-instrument run remained positive and improved in absolute net ticks (`516 -> 534` vs initial baseline).

## Blockers
- None.

## Next Step
- Implement instrument-specific cost calibration in walk-forward (`per-instrument spread/slippage assumptions`) and re-run the same causal benchmark slices.

## Validation
- `PYTHONPATH=src pytest tests/test_morning_plan_walk_forward.py tests/test_signal_engine_setups.py tests/test_config_loading.py tests/test_signal_engine_morning_plan.py -q`
- `PYTHONPATH=src python scripts/run_morning_plan_walk_forward.py --tuning-profile cost_aware_v2 --instrument BRH6 --instrument BRM6 --instrument GDH6 --instrument GDM6 --instrument NGH6 --instrument NGM6 --start-date 2025-10-01 --end-date 2026-03-02 --decision-time 12:00 --train-days 20 --test-days 7 --step-days 7 --offline-only --out-json data/output/research/morning_offline_wf_20251001_20260302_6inst_costawarev2_v1.json`
- `PYTHONPATH=src python scripts/run_morning_plan_walk_forward.py --tuning-profile cost_aware_v2 --instrument ANH6 --instrument BMH6 --instrument BRH6 --instrument CCH6 --instrument CEH6 --instrument DJH6 --instrument DXH6 --instrument FFG6 --instrument GDH6 --instrument GNH6 --instrument HSH6 --instrument KCJ6 --instrument MMH6 --instrument MXH6 --instrument N2H6 --instrument NAH6 --instrument NCH6 --instrument NGH6 --instrument NRH6 --instrument OJH6 --instrument PDH6 --instrument PTH6 --instrument R2H6 --instrument RIH6 --instrument S1H6 --instrument SAH6 --instrument SFH6 --instrument SVH6 --instrument SXH6 --instrument SuG6 --instrument W4H6 --instrument ZCH6 --start-date 2026-01-05 --end-date 2026-03-02 --decision-time 12:00 --train-days 20 --test-days 7 --step-days 7 --offline-only --out-json data/output/research/morning_offline_wf_2026ytd_same_goods_assets_costawarev2_v1.json`
- `python scripts/run_lean_gate.py`
