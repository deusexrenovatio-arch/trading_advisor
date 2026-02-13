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

## Readability rules
- Keep one dominant task per workspace.
- Use compact tables with explicit labels and tooltips.
- Keep action controls near the data they affect.
- Preserve keyboard-friendly filtering and quick reload actions.
