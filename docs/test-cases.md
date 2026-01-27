# Test Suite - Acceptance Coverage

## Purpose
- One place to run manual QA and see automated coverage.
- Each acceptance scenario is linked to one or more test cases.

## Preconditions
- Backend: http://127.0.0.1:8050
- Frontend: http://127.0.0.1:5176
- Data: signal history has at least one day with known stock/future/action.

## Acceptance Mapping (scenario -> test cases)
- decision-view -> TC-DEC-API-001, TC-DEC-UI-001
- decision-view-aggregation -> TC-DEC-API-002
- decision-log-aggregation -> TC-DEC-API-003
- decision-action -> TC-DEC-API-004, TC-DEC-UI-002
- params-specs -> TC-PARAMS-API-001
- top-pairs -> TC-TOP-API-001, TC-TOP-UI-001, TC-TOP-UI-002, TC-TOP-UI-003, TC-TOP-UI-004
- signals-active -> TC-SIG-ACT-API-001, TC-SIG-ACT-UI-001
- signals-history -> TC-SIG-HIST-API-001, TC-SIG-HIST-API-003, TC-SIG-HIST-UI-001, TC-SIG-HIST-UI-002
- signals-history-reasons -> TC-SIG-HIST-API-004
- signals-execute -> TC-SIG-EXEC-API-001, TC-SIG-EXEC-UI-001
- signals-history-range -> TC-SIG-HIST-API-002, TC-SIG-HIST-UI-001
- backtests -> TC-BACK-API-001, TC-BACK-UI-001
- backtest-run -> TC-BACK-V2-API-001, TC-BACK-V2-API-002
- spread-series -> TC-SPREAD-API-001, TC-SPREAD-UI-001
- forward-start -> TC-FWD-API-001
- forward-status -> TC-FWD-API-002
- frontend -> TC-FE-HTTP-001
- frontend-proxy -> TC-FE-PROXY-001
- hpo -> TC-HPO-UNIT-001

## User Scenario Coverage (US -> acceptance/test cases)
- US-01 Configure the strategy -> params-specs (TC-PARAMS-API-001) + unit tests: tests/test_config_resolver.py, tests/test_parameter_specs.py.
- US-02 Daily scan of pairs -> top-pairs, signals-active, signals-history, frontend, frontend-proxy (TC-TOP-*, TC-SIG-ACT-*, TC-SIG-HIST-*, TC-FE-*).
- US-03 Drill into a pair -> spread-series + top-pairs details (TC-SPREAD-API-001, TC-SPREAD-UI-001, TC-TOP-UI-002).
- US-04 Enter a position -> signals-execute + decision-action (TC-SIG-EXEC-API-001, TC-SIG-EXEC-UI-001, TC-DEC-API-004, TC-DEC-UI-002).
- US-05 Early exit (alpha) -> signals-history-reasons + spread-series (TC-SIG-HIST-API-004, TC-SPREAD-API-001) + unit tests: tests/test_spread_carry_alpha.py.
- US-06 Hold to expiry or roll -> signals-history-reasons + spread-series (TC-SIG-HIST-API-004, TC-SPREAD-API-001) + unit tests: tests/test_spread_carry_alpha.py.
- US-07 Backtest review -> backtests (TC-BACK-API-001, TC-BACK-UI-001).
- US-08 Risk/liquidity rejection -> top-pairs + unit checks (TC-TOP-API-001, TC-TOP-UI-001; tests/test_liquidity_metrics.py, tests/test_risk_gate.py).
- US-09 Forward paper daily cycle -> forward-start/forward-status (TC-FWD-API-001, TC-FWD-API-002) + unit tests: tests/test_forward_engine.py.
- US-10 HPO run + leaderboard -> hpo (TC-HPO-UNIT-001) + unit tests: tests/hpo/test_folds.py, tests/hpo/test_objective.py, tests/hpo/test_leaderboard.py.

## UI Test Cases

### TC-DEC-UI-001 Decisions filters, refresh, detail
Acceptance: decision-view
Automation: ui-web/tests/decisions.spec.ts
Steps:
1. Open Decisions tab.
2. Apply Strategy/Instrument/Risk/News filters.
3. Use Quick search.
4. Click Refresh and open a row.
Expected:
- Table rows change according to filters/search.
- Detail panel shows structured decision summary.

### TC-DEC-UI-002 Decision approve/reject flow
Acceptance: decision-action
Automation: ui-web/tests/decisions.spec.ts
Steps:
1. Open Decisions tab and select a decision.
2. Click Approve or Reject.
Expected:
- UI shows operator action status.
- Execution request status is visible.

### TC-TOP-UI-001 Top pairs filters and reload
Acceptance: top-pairs
Automation: ui-web/tests/top-signals.spec.ts
Steps:
1. Open Top pairs tab.
2. Filter by Stock and clear.
3. Click Reload.
Expected:
- Rows update per filter and after reload.
- Columns include spread_pct, rtc_pct, floor_rate_annual, score_floor, total_score, decision.

### TC-TOP-UI-002 Top pairs details chart
Acceptance: top-pairs, spread-series
Automation: ui-web/tests/top-signals.spec.ts
Steps:
1. Open Top pairs.
2. Click Details on a row.
Expected:
- Spread chart renders with data.
- Details panel shows alpha metrics (tp/sl, p_hit_tp/p_hit_sl, sigma_h).

### TC-TOP-UI-003 Top pairs auto refresh indicator
Acceptance: top-pairs
Automation: manual
Steps:
1. Open Top pairs tab.
2. Ensure Auto refresh is enabled.
3. Wait for one refresh interval (60s) or longer.
Expected:
- Updated timestamp changes after the interval.
- Table rows refresh without full page reload.

### TC-TOP-UI-004 Manual recompute updates timestamp
Acceptance: top-pairs
Automation: manual
Steps:
1. Open Top pairs tab.
2. Click Reload (triggers recompute).
Expected:
- Recomputed timestamp updates after the run.
- Table rows refresh with the new snapshot.

### TC-SPREAD-UI-001 Spread chart renders for a pair
Acceptance: spread-series
Automation: ui-web/tests/top-signals.spec.ts
Steps:
1. Open Top pairs.
2. Click Details on a row.
Expected:
- Spread chart renders with spread_mid and spread_pct data.

### TC-SIG-ACT-UI-001 Active signals auto refresh
Acceptance: signals-active
Automation: manual
Steps:
1. Open Signals tab.
2. Ensure Auto refresh is enabled.
3. Wait for one refresh interval (60s) or longer.
Expected:
- Updated timestamp changes after the interval.
- Signals table refreshes without full page reload.


### TC-SIG-HIST-UI-001 Signals history filters and date range
Acceptance: signals-history, signals-history-range
Automation: ui-web/tests/top-signals.spec.ts
Steps:
1. Open Signals tab.
2. Set History from/to and Load history.
3. Apply Stock/Future/Signal filters.
Expected:
- History rows match date range and selected filters.

### TC-SIG-HIST-UI-002 Signals history filters without active signals
Acceptance: signals-history
Automation: ui-web/tests/top-signals.spec.ts
Steps:
1. Ensure active signals list is empty.
2. Load history and apply filters.
Expected:
- History filters apply and row count updates.

### TC-SIG-EXEC-UI-001 Execute signal flow
Acceptance: signals-execute
Automation: ui-web/tests/top-signals.spec.ts
Steps:
1. Open Details for an active signal.
2. Fill Execute form and submit.
Expected:
- Execution history updates with submitted entry.

### TC-BACK-UI-001 Backtests table renders
Acceptance: backtests
Automation: ui-web/tests/top-signals.spec.ts
Steps:
1. Open Backtests tab.
Expected:
- Table shows rows and numeric values render correctly.

### TC-FE-HTTP-001 UI доступен
Acceptance: frontend
Automation: scripts/acceptance_check.py (http_status)
Steps:
1. Open http://127.0.0.1:5176 in browser.
Expected:
- UI loads without errors.

## API Test Cases

### TC-DEC-API-001 Decision view list
Acceptance: decision-view
Automation: scripts/acceptance_check.py (decision-view)
Request:
- GET /api/decision-view?limit=5
Expected:
- JSON list with decision_id, created_at, action, risk_state.

### TC-DEC-API-002 Decision view aggregation field
Acceptance: decision-view-aggregation
Automation: scripts/acceptance_check.py (decision-view-aggregation)
Request:
- GET /api/decision-view?limit=1
Expected:
- aggregation_summary field exists.

### TC-DEC-API-003 Decision log aggregation fields
Acceptance: decision-log-aggregation
Automation: scripts/acceptance_check.py (decision-log-aggregation)
Request:
- GET /api/decision-log/{decision_id}
Expected:
- strategy_signals and aggregation keys exist.

### TC-DEC-API-004 Decision operator action endpoint
Acceptance: decision-action
Automation: scripts/acceptance_check.py (decision-action)
Request:
- POST /api/decisions/{decision_id}/action
Expected:
- status ok and operator_action/execution_status present.

### TC-PARAMS-API-001 Strategy parameter specs
Acceptance: params-specs
Automation: scripts/acceptance_check.py (api_list)
Request:
- GET /api/params/specs
Expected:
- JSON list with key, value_type, default fields.

### TC-TOP-API-001 Top pairs fields and forbidden keys
Acceptance: top-pairs
Automation: scripts/acceptance_check.py (top-pairs)
Request:
- GET /api/top-pairs?limit=5
Expected:
- Required keys include spread_pct, rtc_pct, floor_rate_annual, score_floor, total_score, decision.
- signal_reasons/signal_metrics are absent.

### TC-SIG-ACT-API-001 Active signals actionable
Acceptance: signals-active
Automation: scripts/acceptance_check.py (signals-active)
Request:
- GET /api/signals/active
Expected:
- signal_action only enter/exit.

### TC-SIG-HIST-API-001 History list and allowed actions
Acceptance: signals-history
Automation: scripts/acceptance_check.py (signals-history)
Request:
- GET /api/signals/history?limit=5
Expected:
- Required keys exist, action in enter/exit/hold.

### TC-SIG-HIST-API-002 Date range inclusive
Acceptance: signals-history-range
Automation: scripts/acceptance_check.py (signals-history-range)
Request:
- GET /api/signals/history?from=YYYY-MM-DD&to=YYYY-MM-DD
Expected:
- Inclusive range for the day.

### TC-SIG-HIST-API-003 Filter by stock/future/action
Acceptance: signals-history
Automation: tests/test_signal_api.py
Request:
- GET /api/signals/history?stock=SBER&future=SRH6&signal_action=enter&limit=500
Expected:
- All rows match stock/future/action.

### TC-SIG-HIST-API-004 Signal reasons and metrics present
Acceptance: signals-history-reasons
Automation: scripts/acceptance_check.py (api_list)
Request:
- GET /api/signals/history?limit=5
Expected:
- Each row includes signal_reasons and signal_metrics.

### TC-SIG-EXEC-API-001 Execute signal endpoint
Acceptance: signals-execute
Automation: scripts/acceptance_check.py (post_json)
Request:
- POST /api/signals/execute
Expected:
- 200 OK with JSON response containing status.

### TC-BACK-API-001 Backtests list
Acceptance: backtests
Automation: scripts/acceptance_check.py (backtests)
Request:
- GET /api/backtests?limit=5
Expected:
- JSON list with backtest metrics including share_alpha_exits and avg_hold_days.

### TC-BACK-V2-API-001 Backtest v2 run
Acceptance: backtest-run
Automation: tests/test_backtest_forward_api.py
Request:
- POST /api/backtest/run
Expected:
- JSON response includes summary_metrics, equity_curve, trades.

### TC-BACK-V2-API-002 Backtest v2 validation error
Acceptance: backtest-run
Automation: tests/test_backtest_forward_api.py
Request:
- POST /api/backtest/run (invalid payload)
Expected:
- 400 with validation details.

### TC-SPREAD-API-001 Spread series fields
Acceptance: spread-series
Automation: scripts/acceptance_check.py (spread-series)
Request:
- GET /api/spread-series?stock=...&future=...&window_days=60
Expected:
- Fields spread_mid, spread_pct, entry/exit flags.

### TC-FWD-API-001 Forward start
Acceptance: forward-start
Automation: tests/test_backtest_forward_api.py
Request:
- POST /api/forward/start
Expected:
- Response includes run_id and state payload.

### TC-FWD-API-002 Forward status
Acceptance: forward-status
Automation: tests/test_backtest_forward_api.py
Request:
- GET /api/forward/status
Expected:
- Response includes run_id and last known state.


### TC-FE-PROXY-001 Vite proxy API
Acceptance: frontend-proxy
Automation: scripts/acceptance_check.py (frontend-proxy)
Request:
- GET http://127.0.0.1:5176/api/top-pairs?limit=5
Expected:
- JSON list returned via proxy.

## Unit Test Cases

### TC-HPO-UNIT-001 HPO core behavior
Acceptance: hpo
Automation: tests/hpo/*
Steps:
1. Run `pytest -q tests/hpo`.
Expected:
- Walk-forward folds respect embargo math.
- Constraint violations yield -INF objective.
- Leaderboard orders by objective and best_config matches the top trial.

## Regression Checklist (minimum)
- /api/signals/history returns JSON (no HTML).
- Signals tab loads and renders history table.
- Filters change visible rows (not just the first row).

## Mapping validation
- Run `python scripts/validate_test_cases.py` to ensure acceptance scenarios reference real test cases.
