# Research Evaluation Policy

## Scope
Applies to Backtest v2, HPO, and forward readiness decisions.

## Mandatory experiment contract
- Hypothesis (single sentence)
- Data window (explicit start/end)
- Execution mode (`INTRADAY_MINUTE`, `DAILY_*`)
- Objective metric + mode (`max|min`)
- Hard constraints (drawdown, turnover, risk)

## Acceptance gates
1. Baseline reproducibility:
   - Candidate must be compared to a frozen baseline on the same window.
2. Leakage control:
   - Chronological folds with explicit embargo.
   - Any fallback fold generation must be disclosed.
3. Fold diagnostics:
   - Aggregate objective alone is insufficient.
   - Dispersion metrics (min/median/max or p25/p50/p75) are required.
4. Stress robustness:
   - Cost stress and stricter execution assumptions must be run.
5. Forward sanity:
   - Forward initialization under same assumptions must complete.

## Promotion decision
- `pass`: OOS gain, constraints respected, dispersion acceptable, stress stable, forward sane.
- `hold`: mixed result, missing stress/forward evidence, or weak dispersion.
- `fail`: no OOS gain, constraint breach, instability, or leakage risk.

## Minimum evidence artifacts
- Backtest request payload.
- HPO request payload + status/result.
- Summary report with baseline/candidate/stress.
- Note on fallback folds and residual risks.
