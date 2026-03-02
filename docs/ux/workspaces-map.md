# Workspaces Map

## Navigation model
Top-level workspaces:
1. `Trade Console`
2. `Research Lab`
3. `News Intelligence`
4. `Portfolio Control`

Route map:
1. `Trade Console`
Path: `/trade-console/signals`, `/trade-console/top-pairs`, `/trade-console/backtests`
2. `Decision Audit`
Path: `/decision-audit` (maps to Decisions flow inside Trade Console context)
3. `Research Lab`
Path: `/research-system/backtest-v2`, `/research-system/forward`, `/research-system/hpo`
4. `News Intelligence`
Path: `/news-intelligence`
5. `Portfolio Control`
Path: `/portfolio-control`

## Workspace responsibilities

### Trade Console
- Operator path: signal -> gates -> decision -> action -> audit.
- Subsections: Decisions, Top Pairs, Signals, Backtests.
- Rule: UI displays backend lifecycle and gate states; no domain recomputation.

### Research Lab
- Runs and compares Backtest v2, Forward status, and HPO.
- Supports experiment-centric workflow (`experiment_id`, baseline/candidate/stress).

### News Intelligence
- Aggregated events with severity and links to entities.
- Fast filtering by severity/ticker/entity/time.
- Shows decision references impacted by news context.

### Portfolio Control
- Rebalance preview and commit.
- Shows target weights and risk checks used for approval.

## Entry and Exit Criteria

### Trade Console
- Entry trigger: operator needs to decide or execute now.
- Exit condition: action is logged and history/reasons are reviewable.
- Fallback path: if action is blocked, user is redirected to pre-trade reasons and recovery actions.

### Research Lab
- Entry trigger: operator/researcher needs to validate model behavior before production use.
- Exit condition: run status is deterministic (`completed` or explicit `failed`) and artifacts are inspectable.
- Fallback path: validation errors keep the user in request-edit loop with explicit fields to fix.

### News Intelligence
- Entry trigger: operator suspects event-driven risk impact on current signals.
- Exit condition: relevant events are filtered and linked to impacted decisions/entities.
- Fallback path: empty feed is explicit and does not masquerade as healthy/no-risk state.

### Portfolio Control
- Entry trigger: operator wants to convert active signals into target portfolio weights.
- Exit condition: commit outcome is auditable and risk checks are visible.
- Fallback path: failed risk checks are visible before commit and require explicit mitigation.

### Platform-level operational contract
- Every workspace should expose:
  - last refresh evidence,
  - explicit error state,
  - deterministic retry/reload action.

## Readability rules
- Keep one dominant task per workspace.
- Use compact tables with explicit labels and tooltips.
- Keep action controls near the data they affect.
- Preserve keyboard-friendly filtering and quick reload actions.
