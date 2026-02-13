# Backtest and HPO Evaluation Checklist

## 1) Data and split integrity
- Verify train, val, and test windows are chronological and non-overlapping.
- Verify embargo is explicitly set when serial dependence is material.
- Verify fold count is enough to assess variance (prefer 3+ when possible).
- Verify `folds_meta.fallback` is recorded in report.

## 2) Baseline quality
- Keep one frozen baseline request and artifact.
- Compare every candidate to baseline on same window and execution assumptions.
- Reject candidates with gains only on validation but weak test behavior.

## 3) Objective sanity
- Confirm objective metric and optimization mode before run.
- Confirm metric is business-aligned (for example maximize `excess_ann` under drawdown cap).
- Confirm sign conventions:
  - Raw `MaxDD` is negative in metrics.
  - Objective constraints treat drawdown as absolute magnitude.

## 4) Fold-level diagnostics
- Inspect per-fold objectives, not only aggregate score.
- Track dispersion (min/median/max or p25/median/p75).
- Prefer stable candidates over unstable high-score outliers.

## 5) Robustness
- Re-run with cost stress (`test.cost_stress_mult`).
- Re-run with stricter execution assumptions:
  - `strategy.execution_lag_minutes`
  - `execution.half_spread_bps`
  - `execution.slip_stock_bps`
  - `execution.slip_fut_bps`
- Keep candidate only if ranking remains resilient.

## 6) Forward readiness
- Run forward initialization with same base request assumptions.
- Confirm no hidden dependency on historical artifacts that do not exist forward.
- Flag any mismatch between backtest and forward behavior.

## 7) Promotion gates
- Pass:
  - OOS objective improves vs baseline.
  - Drawdown and turnover within limits.
  - Fold dispersion acceptable.
  - Stress scenario acceptable.
  - Forward sanity check completed.
- Fail:
  - Improvement disappears under stress.
  - High variance across folds with unstable rank.
  - Leakage risk or fallback folds not disclosed.
