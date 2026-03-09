# Research Evaluation Policy

## Scope
Applies to Backtest v2, HPO, and forward readiness decisions.

## Morning-Plan intraday objective (MOEX futures)
- Trading style: intraday level set-and-wait, not scalping.
- Hold horizon: entry and mandatory exit within the same MOEX trading day (`EOD` / before evening clearing).
- Potential setup target: `TP distance >= 0.5%` of entry price.
- Activity target: several entries per week (default optimization band: `2..12` filled trades per week).
- Selection priority: maximize robust net expectancy after costs while respecting the activity band and risk gates.

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
6. Concentration diagnostics:
   - Full-universe result remains the primary decision basis.
   - When one or a few dominant instruments materially drive net revenue, add a supplemental diagnostic without those top contributors and state whether the edge survives.
   - Always report per-instrument or per-root quality and contribution; aggregate net alone is insufficient to claim a structural improvement.
7. Universe hygiene:
   - If both a full and a mini contract exist for the same underlying, exclude the mini contract from whole-universe evaluation by default.
   - Human-facing reports should refer to roots as `TICKER (Name)`.
8. Calendar diagnostics:
   - Month-level reporting must distinguish active trading months from the full calendar inside the requested window.
   - Months with no filled trades count as flat months and must be disclosed explicitly.
9. Thin-root diagnostics:
   - `thin-sample` is a confidence flag, not a diagnosis.
   - Sparse roots must be classified by cause before any pruning decision: `immature history`, `sparse-trigger`, `current-regime silent`, or `strategy-fit review`.
   - When current-regime silent roots cluster in one family, record the family-level hypothesis explicitly instead of treating them as isolated root failures.

## Promotion decision
- `pass`: OOS gain, constraints respected, dispersion acceptable, stress stable, forward sane.
- `hold`: mixed result, missing stress/forward evidence, or weak dispersion.
- `fail`: no OOS gain, constraint breach, instability, or leakage risk.

## Minimum evidence artifacts
- Backtest request payload.
- HPO request payload + status/result.
- Summary report with baseline/candidate/stress.
- Note on fallback folds and residual risks.
- Per-instrument or per-root contribution table, plus a no-dominant-top diagnostic when concentration is material.
- Active-month and full-calendar month summary, including flat no-fill months.
