# Space Organization v2

## Goal
Keep core operator flows readable while new modules (news, futures speculation, portfolio controls) are added.

## Workspace layout
1. `Trade Console`
Path: `/trade-console/*`
Focus: active market actions (`signals`, `top-pairs`, `backtests`) and quick execution.
2. `Decision Audit`
Path: `/decision-audit`
Focus: explainability and audit lifecycle of decision records.
3. `Research System`
Path: `/research-system/*`
Focus: backtest/forward/HPO experiments and promotion checks.
4. `News Intelligence`
Path: `/news-intelligence`
Focus: event severity, entity links, signal impact context.
5. `Portfolio Control`
Path: `/portfolio-control`
Focus: rebalance proposals, risk checks, commit trail.

## UI boundary rule
Business statuses are backend-owned.
Frontend must render `signal_action_effective` and lifecycle from API contracts and cannot recompute them from local pretrade/lifecycle conditions.

## Trade Console composition
- `SignalQueuePanel`: compact list of open positions with effective action.
- `DecisionPanel`: effective signal state + gate chips + open-position badge.
- `PretradePanel`: ISS pre-trade status, blocking reasons, order corridor, diagnostics.
- `ExecutionPanel`: operator action form and execution history.
- `DecisionHistoryPanel`: filtered historical signal stream.

## UX intent
Signal handling (`signal -> pretrade -> action -> audit`) stays in one workspace flow without context switching between independent tabs.

## Workspace KPI strip
- Show compact session counters near workspace tabs:
  - `tab_switch_count`
  - `time_to_first_action_sec`
  - `blocked_action_rate`
- Use them as operator-friction indicators, not as domain risk signals.
