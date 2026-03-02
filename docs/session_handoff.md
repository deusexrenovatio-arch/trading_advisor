# Session Handoff
Updated: 2026-03-02 14:56 UTC

## Goal
- Improve morning-plan profitability robustness on broad commodity futures universe using strictly causal walk-forward.

## Current Delta
- Added robust train selection and coverage thresholds in walk-forward runner.
- Added setup-level cost-aware net gate and ATR-vs-cost eligibility filter.
- Added tuning profiles in runner (`baseline_v1`, `cost_aware_v2`) and validated `cost_aware_v2` on 6/32 slices.
- Added optional instrument-specific cost profile (`train_proxy_v1`) derived only from train-window M5 proxies.
- Added reporting fields: `tuning_points.cost_model_profile` and per-fold `cost_assumptions_by_instrument`.
- Added tests for tuning profile resolution and cost-model profile/calibration helpers.
- Causal results: `cost_aware_v2` improved 32-inst to near breakeven (`net -32`), while `train_proxy_v1` is more conservative (`net -73`).

## Blockers
- None.

## Next Step
- Implement Priority #6: connect probabilistic outcome layer/gate to morning-plan candidates (Dirichlet baseline + expected-net gate).

## Validation
- `PYTHONPATH=src pytest tests/test_morning_plan_walk_forward.py tests/test_signal_engine_setups.py tests/test_config_loading.py tests/test_signal_engine_morning_plan.py -q`
- `PYTHONPATH=src python scripts/run_morning_plan_walk_forward.py --tuning-profile cost_aware_v2 --cost-model-profile fixed_v1 --instrument ANH6 --instrument BMH6 --instrument BRH6 --instrument CCH6 --instrument CEH6 --instrument DJH6 --instrument DXH6 --instrument FFG6 --instrument GDH6 --instrument GNH6 --instrument HSH6 --instrument KCJ6 --instrument MMH6 --instrument MXH6 --instrument N2H6 --instrument NAH6 --instrument NCH6 --instrument NGH6 --instrument NRH6 --instrument OJH6 --instrument PDH6 --instrument PTH6 --instrument R2H6 --instrument RIH6 --instrument S1H6 --instrument SAH6 --instrument SFH6 --instrument SVH6 --instrument SXH6 --instrument SuG6 --instrument W4H6 --instrument ZCH6 --start-date 2026-01-05 --end-date 2026-03-02 --decision-time 12:00 --train-days 20 --test-days 7 --step-days 7 --offline-only --out-json data/output/research/morning_offline_wf_2026ytd_same_goods_assets_costawarev2_v1.json`
- `PYTHONPATH=src python scripts/run_morning_plan_walk_forward.py --tuning-profile cost_aware_v2 --cost-model-profile train_proxy_v1 --instrument ANH6 --instrument BMH6 --instrument BRH6 --instrument CCH6 --instrument CEH6 --instrument DJH6 --instrument DXH6 --instrument FFG6 --instrument GDH6 --instrument GNH6 --instrument HSH6 --instrument KCJ6 --instrument MMH6 --instrument MXH6 --instrument N2H6 --instrument NAH6 --instrument NCH6 --instrument NGH6 --instrument NRH6 --instrument OJH6 --instrument PDH6 --instrument PTH6 --instrument R2H6 --instrument RIH6 --instrument S1H6 --instrument SAH6 --instrument SFH6 --instrument SVH6 --instrument SXH6 --instrument SuG6 --instrument W4H6 --instrument ZCH6 --start-date 2026-01-05 --end-date 2026-03-02 --decision-time 12:00 --train-days 20 --test-days 7 --step-days 7 --offline-only --out-json data/output/research/morning_offline_wf_2026ytd_same_goods_assets_costawarev2_costproxy_v1.json`
- `python scripts/run_lean_gate.py`
