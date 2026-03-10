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
- `need-signal-action-control-loop`: action API + Telegram review/follow-up bridge + auto-remediation policy.
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
    `signals-execute`, `signals-ack-execute`, `signals-actionability-h4a-followup`, `signals-history`,
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

## Fresh component-first review (2026-03-02)

### Review order (end-to-end operator path)
1. Platform entry and workspace navigation (`/trade-console`, `/research-system`, `/news-intelligence`, `/portfolio-control`).
2. Trade Console: Decisions audit.
3. Trade Console: Top pairs and Signals execution loop (including pre-trade and action logging).
4. Trade Console: Backtests snapshot review.
5. Research Lab: Backtest v2, Forward status, HPO run/status.
6. News Intelligence: severity/entity filtering and decision linkage.
7. Portfolio Control: rebalance preview and commit.
8. Ops and integration reliability: refresh scheduler state, SLO/health APIs, Telegram review/follow-up bridge.

### Component outcomes and success criteria
| Component | Primary user job | Success signal |
| --- | --- | --- |
| Platform entry + routing | Reach the right workspace in one transition | Correct canonical route, no dead-end tabs |
| Decisions audit | Filter decisions and make explicit operator action | Action is persisted, execution status is visible |
| Top pairs + Signals | Move from opportunity to safe action | Actionability, gates, execution, and history stay coherent |
| Backtests table | Validate recent strategy outcomes quickly | Key metrics stay readable and drilldowns stay available |
| Backtest v2 (Research) | Run controlled experiment with explicit params | Deterministic report with summary/equity/trades |
| Forward status | Inspect live paper-cycle state | Latest state/equity/trade/alert visible without raw file reads |
| HPO | Start and monitor optimization with quality signals | Run id, progress, leaderboard, and completion gate are explicit |
| News Intelligence | Understand event pressure on decisions | Severity and entity filters reduce noise without losing traceability |
| Portfolio Control | Approve rebalance with visible risk checks | Plan and risk checks are explicit before commit |
| Ops and scheduler visibility | Trust runtime freshness and degradation states | Health/SLO/refresh status are actionable and timely |
| Telegram review/follow-up bridge | Confirm review and H4A follow-up quickly, then continue in UI | Review, follow-up confirmation, and execution remain linked and auditable |

### Coverage stress-test by component
- `Trade Console / Decisions`:
  - Primary: filter and submit operator action.
  - Edge: empty result after filters or no decision detail payload.
  - Negative: action submission fails or returns duplicate.
  - Interruption: page reload after action should preserve status via server projection.
- `Trade Console / Signals`:
  - Primary: inspect actionable signal -> pre-trade -> execute -> verify history.
  - Edge: position already open, repriced intent, or hold overlay.
  - Negative: fail-closed block, stale intent, ambiguous instrument mapping.
  - Interruption: repeated submit must be idempotent, not duplicate execution.
- `Trade Console / Top pairs + spread chart`:
  - Primary: ranked opportunities plus spread drilldown.
  - Edge: data source fallback (unified -> legacy).
  - Negative: missing pair parameters returns explicit API error.
  - Interruption: cache TTL reload should not break chart or sort context.
- `Research Lab / Backtest v2`:
  - Primary: paramized run with report output.
  - Edge: large param set or filtered param list.
  - Negative: validation_error or missing data window.
  - Interruption: rerun with same payload should remain reproducible.
- `Research Lab / HPO`:
  - Primary: submit run and track progress to completion.
  - Edge: JSON override + form default merge.
  - Negative: invalid JSON, invalid date range, quality gate fail.
  - Interruption: browser remains usable during async polling cycles.
- `Research Lab / Forward`:
  - Primary: inspect current run health.
  - Edge: run_id omitted (latest run fallback).
  - Negative: no active run or backend error.
  - Interruption: repeated status polling does not mutate run state.
- `News Intelligence`:
  - Primary: filter by severity/ticker and inspect decision links.
  - Edge: sparse event windows.
  - Negative: malformed date/severity filters.
  - Interruption: manual refresh keeps filter state.
- `Portfolio Control`:
  - Primary: preview target weights and commit.
  - Edge: partial or empty position list.
  - Negative: failed risk checks before commit.
  - Interruption: repeated commit attempts must be auditable and safe.
- `Ops + scheduler + integrations`:
  - Primary: monitor health/SLO and refresh progression.
  - Edge: `scheduled_follower`, `busy`, or `degraded` scheduler states.
  - Negative: transport degradation and auto-unwind errors.
  - Interruption: worker retries and callback expiration must not create spam loops.

### Highest-priority gaps from fresh review
1. `P0` (resolved 2026-03-02): UI action payloads in `Signals` and `Decisions` now include explicit `idempotency_key` for v2 write APIs.
2. `P0` (resolved 2026-03-02): Portfolio rebalance commit path now hard-blocks on failed `max_positions` risk gate.
3. `P1` (resolved 2026-03-02): Forward workspace now has operator start action (`POST /api/forward/start`) in the same flow as status.
4. `P1` (open): Runtime degradation states (`busy/degraded/error`) are exposed by API but only partially surfaced as guided operator actions.
5. `P1` (open): Instrument action endpoint can return ambiguity (`candidate_pairs`), but UI guidance for this recovery path is not yet explicit.

## First-Time-Right report block
1. Confirmed coverage:
   - All major user-visible components are now reviewed in sequence with primary/edge/negative/interruption flows.
   - Existing catalog remains acceptance-linked and CI-valid.
2. Missing or risky scenarios:
   - Degradation recovery UX still lacks explicit guided actions for `busy/degraded/error` states.
   - Instrument ambiguity path still needs first-class UI branch for `candidate_pairs`.
3. Resource/time risks and controls:
   - Risk: broad scenario expansion can bloat context and delay delivery.
   - Control: component-first order and explicit P0/P1 prioritization, with acceptance-linked updates only.
4. Highest-priority fixes or follow-ups:
   - Extend Research and Ops UX for explicit degradation recovery actions.
   - Add explicit UI resolution flow for ambiguous instrument action response.
