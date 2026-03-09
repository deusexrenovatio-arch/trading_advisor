# Walk-Forward Baseline Decisions (2026-03-04)

## Selected Baseline
- Baseline report: `artifacts/research/wf_goal_v6_mad_neg8_seed111_wt_signal_engine_rerun_20260304.json`
- Why selected:
  - Positive net on wide universe and long causal period.
  - Better TP/SL balance than `robust_normalized` reruns with same constraints.
  - Uses conservative train-coverage and negative-period penalties.

## Baseline Spec
- Universe: 66 instruments (front-nearest roots from prior `v6` runs).
- Period: `2025-03-01` to `2026-03-02`.
- Decision times: `10:30, 12:00, 14:00` (MSK).
- Walk-forward: `train=28`, `test=7`, `step=7`, `retune_every=3`.
- Objective: `robust_median_mad`, `robust_mad_penalty=0.5`.
- Stability penalty: `objective_negative_fold_penalty=8`, `objective_subfold_days=7`.
- Coverage gates: `min_train_trades=80`, `min_train_instruments_with_trades=10`, `min_trades_per_instrument=5`.
- Cost model: `train_proxy_v1`.
- Search profile: `intraday_goal_v3`, algorithm `TPE`, `hpo_trials=24`, `hpo_startup_trials=8`, `seed=111`.

## Rerun Comparison (same baseline window)
- Aggregated table: `artifacts/research/wf_goal_v6_rerun_compare_20260304.json`
- `negpen8 + robust_normalized + prob_gate(10/1.0)`:
  - `net_ticks_sum=5966.0`, folds `14+/11-/28 zero`, `filled=71`.
- `negpen8 + robust_normalized`:
  - same as above (probability gate had no impact in current code/data state).
- `negpen0 + robust_normalized`:
  - `net_ticks_sum=5375.5`, folds `9+/16-/28 zero`, `filled=76`.
- `negpen8 + robust_median_mad` (selected baseline):
  - `net_ticks_sum=6203.0`, folds `14+/11-/28 zero`, `filled=71`.

## Accepted Changes
- Keep negative-period penalty (`objective_negative_fold_penalty=8`): improves fold balance and net vs `negpen0`.
- Keep robust objective family and use `robust_median_mad` baseline for now.
- Keep strict train coverage (`80/10/5`) as baseline contract.

## Rejected / Retired For Now
- `intraday_goal_v4_clustered` search-space profile:
  - no durable uplift in latest comparisons; removed from active runner choices.
- `fold_stability` selection objective:
  - no durable uplift in latest comparisons; removed from active runner choices.
- Probability-gate threshold sweeps (`n_eff=10/20`, `ER=1.0/1.5`) as optimization lever:
  - no measurable effect in current reruns (identical outcomes); keep gate code, stop using this as primary tuning axis.

## Do-Not-Retest List (until data/model regime changes)
- `objective_negative_fold_penalty=0` as primary setting.
- `probability_gate` threshold-only retunes without other structural changes.
- `intraday_goal_v4_clustered` and `fold_stability` in main tuning loop.
