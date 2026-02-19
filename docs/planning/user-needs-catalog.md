# User Needs Catalog

## Purpose
- Make expected user value explicit before implementation.
- Keep CI aligned with user-facing outcomes, not only technical correctness.

## Source of truth
- Structured catalog: `configs/user_needs_catalog.yaml`.
- CI validation: `python scripts/validate_user_needs_catalog.py`.
- Current policy: full catalog coverage of acceptance scenarios is required in CI.

## New priority needs
- `need-complete-user-facing-flow`: user can move from signal review to safe execution without hidden scenario gaps.
- `need-fast-convergence-to-target`: tuning starts from explicit target metric and acceptance contract.
- `need-runtime-transparency-and-control`: long tasks expose ETA, checkpoints, and stop/replan triggers.
- `need-high-load-by-design`: heavy jobs are chunked, parallelized with limits, and resumable.
- `need-context-integrity`: every change maps to the main objective and user value.
- `need-predictive-evolution`: likely next user needs are considered before finalizing design.
- `need-decision-audit-review`: filtered decision audit with aggregation drilldown.
- `need-market-scan-history-analysis`: top-pairs, spread drilldown, and signal history coherence.
- `need-signal-action-control-loop`: action API + ACK bridge + auto-remediation policy.
- `need-research-backtest-forward-lifecycle`: backtest/run/forward cycle plus UI trigger path.
- `need-ui-platform-entry-and-proxy`: frontend health and proxy contract reliability.
- `need-news-portfolio-ops-observability`: news workspace, portfolio control, runtime observability.
- `need-delivery-governance-baseline`: mandatory stream-start and pre-push governance coverage.

## New user-case focus
- Actionable signal -> execution in one coherent flow.
- Safe fail-closed path for degraded/stale pretrade data.
- Target-locked tuning workflow for faster convergence.
- Long operation control with interrupt/replan behavior.
- High-load batch execution with chunking/resume.
- Scope drift prevention against main objective.
- Repeated issue escalation to structured root-cause review.
- Extension-ready design for near-term feature evolution.

## Coverage matrix (acceptance scenario groups)
- Process governance:
  - `dev-skill-start-gate`, `dev-skill-recheck-gate`, `dev-skill-prepush-gate`,
    `first-time-right-goal-contract-gate`, `first-time-right-user-case-gate`,
    `first-time-right-budget-stop-gate`, `first-time-right-load-readiness-gate`,
    `first-time-right-context-integrity-gate`, `first-time-right-repeated-issue-gate`
- Decision and audit:
  - `decision-view`, `decision-view-filters`, `decision-view-aggregation`,
    `decision-log-aggregation`, `decision-action`
- Market scan and signal lifecycle:
  - `top-pairs`, `spread-series`, `signals-active`, `signals-action-v2`,
    `signals-execute`, `signals-ack-execute`, `signals-history`,
    `signals-history-range`, `signals-history-reasons`, `pretrade-check`,
    `auto-unwind-policy-v2`
- Research and runtime:
  - `params-specs`, `hpo`, `hpo-status`, `backtests`, `backtest-run`,
    `forward-start`, `forward-status`, `unified-minute-runtime`, `frontend-hpo-run`
- UI and integration surfaces:
  - `frontend`, `frontend-proxy`, `frontend-params-specs`
- News, portfolio, ops:
  - `news-feed-v2`, `portfolio-rebalance-v2`, `ops-health-v2`, `ops-slo-v2`

## Verification
- Run:
  - `python scripts/validate_user_needs_catalog.py`
- Expected:
  - Validation passes with full acceptance scenario coverage.
