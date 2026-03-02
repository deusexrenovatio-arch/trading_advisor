# Session Handoff
Updated: 2026-03-02 21:09 UTC

## Goal
- Improve morning-plan profitability robustness on broad commodity futures universe using strictly causal walk-forward.

## Current Delta
- Added robust train selection, setup cost/net gate, ATR-vs-cost eligibility, and `cost_aware_v2` tuning profile.
- Added optional probability gate in runner test phase with Dirichlet-decay forecasts and train-history bootstrap.
- Probability gate controls include `--prob-min-n-effective`, `--prob-min-expected-return-ticks`, and context mode.
- Added fold trade-floor safeguard via `--prob-min-filled-trades-per-fold` with ungated fallback metadata per fold.
- Added per-fold cost payloads and probability-gate settings to report JSON.
- Added tests for tuning/cost/probability helper paths in `tests/test_morning_plan_walk_forward.py`.
- Latest baseline on 32 instruments: `net -32` with 22 trades; gated `n_eff>=1, er>=1.0` gives `net +226` with only 5 trades.
- With floor safeguard (`min-filled-per-fold=2`) gated result is `net -136` on 18 trades; softer gate (`n_eff>=0`) gives `net 0` on 17 trades.

## Blockers
- None.

## Next Step
- Keep probability gate disabled by default; investigate outlier fold concentration and rework context/binning before enabling gate profile.

## Validation
- `PYTHONPATH=src pytest tests/test_morning_plan_walk_forward.py tests/test_signal_engine_setups.py tests/test_config_loading.py tests/test_signal_engine_morning_plan.py -q`
- `PYTHONPATH=src python scripts/run_morning_plan_walk_forward.py --tuning-profile cost_aware_v2 --cost-model-profile fixed_v1 --instrument ANH6 --instrument BMH6 --instrument BRH6 --instrument CCH6 --instrument CEH6 --instrument DJH6 --instrument DXH6 --instrument FFG6 --instrument GDH6 --instrument GNH6 --instrument HSH6 --instrument KCJ6 --instrument MMH6 --instrument MXH6 --instrument N2H6 --instrument NAH6 --instrument NCH6 --instrument NGH6 --instrument NRH6 --instrument OJH6 --instrument PDH6 --instrument PTH6 --instrument R2H6 --instrument RIH6 --instrument S1H6 --instrument SAH6 --instrument SFH6 --instrument SVH6 --instrument SXH6 --instrument SuG6 --instrument W4H6 --instrument ZCH6 --start-date 2026-01-05 --end-date 2026-03-02 --decision-time 12:00 --train-days 20 --test-days 7 --step-days 7 --offline-only --out-json data/output/research/morning_offline_wf_2026ytd_same_goods_assets_costawarev2_v1.json`
- `PYTHONPATH=src python scripts/run_morning_plan_walk_forward.py --tuning-profile cost_aware_v2 --cost-model-profile fixed_v1 --enable-probability-gate --prob-context-mode setup_group_side --prob-min-n-effective 1 --prob-min-expected-return-ticks 1.0 --instrument ANH6 --instrument BMH6 --instrument BRH6 --instrument CCH6 --instrument CEH6 --instrument DJH6 --instrument DXH6 --instrument FFG6 --instrument GDH6 --instrument GNH6 --instrument HSH6 --instrument KCJ6 --instrument MMH6 --instrument MXH6 --instrument N2H6 --instrument NAH6 --instrument NCH6 --instrument NGH6 --instrument NRH6 --instrument OJH6 --instrument PDH6 --instrument PTH6 --instrument R2H6 --instrument RIH6 --instrument S1H6 --instrument SAH6 --instrument SFH6 --instrument SVH6 --instrument SXH6 --instrument SuG6 --instrument W4H6 --instrument ZCH6 --start-date 2026-01-05 --end-date 2026-03-02 --decision-time 12:00 --train-days 20 --test-days 7 --step-days 7 --offline-only --out-json data/output/research/morning_offline_wf_2026ytd_same_goods_assets_probgate_v2_calib1.json`
- `PYTHONPATH=src python scripts/run_morning_plan_walk_forward.py --tuning-profile cost_aware_v2 --cost-model-profile fixed_v1 --enable-probability-gate --prob-context-mode setup_group_side --prob-min-n-effective 1 --prob-min-expected-return-ticks 1.0 --prob-min-filled-trades-per-fold 2 --instrument ANH6 --instrument BMH6 --instrument BRH6 --instrument CCH6 --instrument CEH6 --instrument DJH6 --instrument DXH6 --instrument FFG6 --instrument GDH6 --instrument GNH6 --instrument HSH6 --instrument KCJ6 --instrument MMH6 --instrument MXH6 --instrument N2H6 --instrument NAH6 --instrument NCH6 --instrument NGH6 --instrument NRH6 --instrument OJH6 --instrument PDH6 --instrument PTH6 --instrument R2H6 --instrument RIH6 --instrument S1H6 --instrument SAH6 --instrument SFH6 --instrument SVH6 --instrument SXH6 --instrument SuG6 --instrument W4H6 --instrument ZCH6 --start-date 2026-01-05 --end-date 2026-03-02 --decision-time 12:00 --train-days 20 --test-days 7 --step-days 7 --offline-only --out-json data/output/research/morning_offline_wf_2026ytd_goods32_costawarev2_fixed_probgate_sgs_ne1_er1p0_floor2.json`
- `python scripts/run_lean_gate.py`
