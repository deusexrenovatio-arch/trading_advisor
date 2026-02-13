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
- decision-view-filters -> TC-DEC-API-005
- decision-view-aggregation -> TC-DEC-API-002
- decision-log-aggregation -> TC-DEC-API-003
- decision-action -> TC-DEC-API-004, TC-DEC-UI-002
- params-specs -> TC-PARAMS-API-001
- frontend-params-specs -> TC-BACK-V2-UI-001, TC-BACK-V2-UI-002
- top-pairs -> TC-TOP-API-001, TC-TOP-UI-001, TC-TOP-UI-002, TC-TOP-UI-003, TC-TOP-UI-004
- signals-active -> TC-SIG-ACT-API-001, TC-SIG-ACT-API-002, TC-SIG-CONTRACT-API-001, TC-SIG-ACT-UI-001
- signals-history -> TC-SIG-HIST-API-001, TC-SIG-HIST-API-003, TC-SIG-CONTRACT-API-001, TC-SIG-HIST-UI-001, TC-SIG-HIST-UI-002
- signals-history-reasons -> TC-SIG-HIST-API-004
- signals-execute -> TC-SIG-EXEC-API-001, TC-SIG-EXEC-API-002, TC-SIG-EXEC-API-003, TC-SIG-EXEC-UI-001, TC-SIG-EXEC-UI-002
- auto-unwind-policy-v2 -> TC-SIG-POLICY-API-001
- pretrade-check -> TC-PRETRADE-API-001, TC-PRETRADE-API-002, TC-PRETRADE-UI-001
- signals-history-range -> TC-SIG-HIST-API-002, TC-SIG-HIST-UI-001
- backtests -> TC-BACK-API-001, TC-BACK-UI-001
- backtest-run -> TC-BACK-V2-API-001, TC-BACK-V2-API-002
- spread-series -> TC-SPREAD-API-001, TC-SPREAD-UI-001
- forward-start -> TC-FWD-API-001
- forward-status -> TC-FWD-API-002
- frontend -> TC-FE-HTTP-001
- frontend-proxy -> TC-FE-PROXY-001
- hpo -> TC-HPO-API-001, TC-HPO-UNIT-001
- hpo-status -> TC-HPO-API-002
- ui-domain-boundary -> TC-UI-DOMAIN-001
- workspace-routing -> TC-UI-ROUTE-001
- workspace-kpi -> TC-UI-KPI-001
- signals-workspace-flow -> TC-SIG-UI-WORKFLOW-001
- news-feed-v2 -> TC-NEWS-API-001, TC-NEWS-UI-001
- portfolio-rebalance-v2 -> TC-PORT-API-001, TC-PORT-UI-001
- ops-health-v2 -> TC-OPS-API-001
- ops-slo-v2 -> TC-OPS-API-002

## User Scenario Coverage (US -> acceptance/test cases)
- US-01 Configure the strategy -> params-specs (TC-PARAMS-API-001) + unit tests: tests/test_config_resolver.py, tests/test_parameter_specs.py.
- US-02 Daily scan of pairs -> top-pairs, signals-active, signals-history, frontend, frontend-proxy (TC-TOP-*, TC-SIG-ACT-*, TC-SIG-HIST-*, TC-FE-*).
- US-03 Drill into a pair -> spread-series + top-pairs details (TC-SPREAD-API-001, TC-SPREAD-UI-001, TC-TOP-UI-002).
- US-04 Enter a position -> signals-execute + pretrade-check + decision-action (TC-SIG-EXEC-API-001, TC-SIG-EXEC-API-002, TC-SIG-EXEC-UI-001, TC-SIG-EXEC-UI-002, TC-PRETRADE-API-001, TC-PRETRADE-UI-001, TC-DEC-API-004, TC-DEC-UI-002).
- US-04 Enter a position -> fail-closed guard on degraded/pretrade-unknown entry (tests/test_api_v2.py).
- US-05 Early exit (alpha) -> signals-history-reasons + spread-series (TC-SIG-HIST-API-004, TC-SPREAD-API-001) + unit tests: tests/test_spread_carry_alpha.py.
- US-06 Hold to expiry or roll -> signals-history-reasons + spread-series (TC-SIG-HIST-API-004, TC-SPREAD-API-001) + unit tests: tests/test_spread_carry_alpha.py.
- US-07 Backtest review -> backtests (TC-BACK-API-001, TC-BACK-UI-001).
- US-08 Risk/liquidity rejection -> top-pairs + unit checks (TC-TOP-API-001, TC-TOP-UI-001; tests/test_liquidity_metrics.py, tests/test_risk_gate.py).
- US-09 Forward paper daily cycle -> forward-start/forward-status (TC-FWD-API-001, TC-FWD-API-002) + unit tests: tests/test_forward_engine.py.
- US-10 HPO run + leaderboard -> hpo, hpo-status (TC-HPO-API-001, TC-HPO-API-002, TC-HPO-UNIT-001) + unit tests: tests/hpo/test_folds.py, tests/hpo/test_objective.py, tests/hpo/test_leaderboard.py.
- US-11 Review decisions with server filters -> decision-view, decision-view-filters (TC-DEC-API-001, TC-DEC-API-005, TC-DEC-UI-001).

## UI Test Cases

### TC-UI-DOMAIN-001 Frontend must not compute business signal statuses
Acceptance: ui-domain-boundary
Automation: ui-web/scripts/ui-domain-boundary-gate.mjs
Steps:
1. Run `npm --prefix ui-web run lint:ui-domain-boundary`.
Expected:
- Check fails if UI computes `signal_action_effective` from pretrade/lifecycle logic.
- Check passes only when `signal_action_effective` is consumed from backend payload.

### TC-UI-ROUTE-001 Workspace routes keep tab context
Acceptance: workspace-routing
Automation: manual
Steps:
1. Open `/trade-console/signals`, `/decision-audit`, `/research-system/backtest-v2`.
2. Switch workspace tabs and verify URL changes.
3. Refresh page on each URL.
Expected:
- Workspace and tab state restore from URL.
- Invalid routes normalize to `/trade-console/signals`.

### TC-UI-KPI-001 Workspace KPI counters are visible and updated
Acceptance: workspace-kpi
Automation: manual
Steps:
1. Open `/trade-console/signals`.
2. Switch between `Trade Console`, `Research Lab`, `News Intelligence`.
3. Trigger one operator action (`approve/reject` decision or `execute` signal).
Expected:
- KPI panel shows `tab_switch_count`, `time_to_first_action_sec`, `blocked_action_rate`.
- `tab_switch_count` increases after route/workspace changes.
- `time_to_first_action_sec` changes from `n/a` to a numeric value after first action.

### TC-NEWS-UI-001 News workspace route and feed filters
Acceptance: news-feed-v2
Automation: ui-web/tests/workspace-news-portfolio.spec.ts
Steps:
1. Open `/news-intelligence` from workspace tabs.
2. Apply `Ticker` and `Severity` filters.
3. Reload feed.
Expected:
- URL is stable (`/news-intelligence`) after refresh.
- Feed rows respect ticker/severity filters.
- Event row shows severity, headline, ticker link, and decision reference when present.

### TC-PORT-UI-001 Portfolio workspace preview and commit
Acceptance: portfolio-rebalance-v2
Automation: ui-web/tests/workspace-news-portfolio.spec.ts
Steps:
1. Open `/portfolio-control` from workspace tabs.
2. Load rebalance preview and inspect positions table.
3. Commit rebalance plan.
Expected:
- Preview table shows `entity_ref`, target weight, lifecycle, signal action, score.
- Commit request is sent with `rebalance_plan_id` and positions list.
- UI shows success status with commit id and number of committed positions.

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

### TC-DEC-API-005 Decision view server-side filters
Acceptance: decision-view-filters
Automation: scripts/acceptance_check.py
Steps:
1. Call `/api/decision-view` with `strategy_type`, `primary_instrument`, `risk_state`, `news_severity`, `created_from`, `created_to`.
Expected:
- API returns a JSON array (can be empty).
- If rows exist, they include `decision_id` and respect filter fields.

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
- Main `Сигнал` column reflects effective action with pre-trade constraints even before opening details.
- Open positions remain visible with explicit `hold_open` status until an `exit` is logged.
- Signals table includes action fields for execution planning:
  - `entry_stock_min` / `entry_stock_max`,
  - `entry_future_min_per_share` / `entry_future_max_per_share`,
  - `tp_spread_pct_level` / `sl_spread_pct_level`,
  - `forecast_exit_days`.

### TC-SIG-UI-WORKFLOW-001 Signal workspace flow in single detail context
Acceptance: signals-workspace-flow
Automation: manual
Steps:
1. Open `/trade-console/signals`.
2. Expand a signal row with details.
3. Verify blocks `Итоговый сигнал`, `Pre-trade проверка (ISS)`, `Исполнить сигнал`, `История исполнений`.
4. Refresh pre-trade and then submit execution action when enabled.
Expected:
- Operator sees decision, blockers, and action controls in one detail flow.
- `PretradePanel` and `ExecutionPanel` render without switching to other screens.
- Execution history updates in the same expanded row context.

### TC-SIG-PLAN-UI-001 Signals trading plan layout
Acceptance: signals-active
Automation: ui-web/tests/top-signals.spec.ts
Steps:
1. Open Signals tab.
2. Check table headers for execution-planning fields.
3. Open Details for an active signal.
4. Switch to detail tab `Сигнал`.
Expected:
- Table renders `entry_stock_min`, `entry_stock_max`, `entry_future_min_per_share`, `entry_future_max_per_share`, `tp_spread_pct_level`, `sl_spread_pct_level`, `forecast_exit_days`.
- Entry columns are rendered as concrete prices; risk/forecast columns keep percent/days formatting where applicable.
- Detail panel groups metrics into blocks: `Контекст сигнала`, `Итоговый сигнал`, `План входа`, `Риск и стоп-уровни`, `Прогноз выхода`.
- `Итоговый сигнал` расположен выше `Плана входа` и учитывает pre-trade (`hold_pretrade`/`check_pretrade` для входа при ограничениях).
- If plan fields are missing in API payload, UI shows explicit coverage counters and a non-blocking note (instead of empty broken tabs).
- `Обзор` / `Альфа` / `Ликвидность` tabs in Signals details appear only when the selected signal row has data for them.


### TC-SIG-HIST-UI-001 Signals history filters and date range
Acceptance: signals-history, signals-history-range
Automation: ui-web/tests/top-signals.spec.ts
Steps:
1. Open Signals tab.
2. Set History from/to and Load history.
3. Apply Stock/Future/Signal filters.
Expected:
- History rows match date range and selected filters.
- `Сигнал` filter in Signals tab uses effective statuses from main table; for history API it maps pre-trade statuses to `enter`.

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
- Form contains `Цена`, `Кол-во`, `Нога сделки`, `Комментарий` (without manual status field).
- Execution history updates with submitted entry.

### TC-SIG-EXEC-UI-002 Link two legs by one order_id
Acceptance: signals-execute
Automation: ui-web/tests/top-signals.spec.ts
Steps:
1. Open Details for an active signal.
2. Submit first leg (`stock`).
3. Submit second leg (`future`) for the same pair and action.
Expected:
- Both requests are accepted.
- API payload contains `order_id`.
- `order_id` is identical for both legs, enabling linked two-leg execution tracking.

### TC-PRETRADE-UI-001 Signals pre-trade panel
Acceptance: pretrade-check
Automation: ui-web/tests/top-signals.spec.ts
Steps:
1. Open Details for an active `enter` signal in Signals tab.
2. Verify pre-trade panel is shown.
3. Verify visible blocks: summary status, blocking reasons, critical entry gates, order corridor, volume requirements.
4. Expand `Расширенная диагностика` and verify snapshot counters are rendered.
Expected:
- Panel displays current status and reasons.
- Operator sees both-leg constraints before manual order placement.
- Technical diagnostics are available on demand and do not overload default view.
- Button `Исполнить` для входного сигнала недоступна, пока pre-trade не подтверждает `ready_to_place=true`.

### TC-BACK-UI-001 Backtests table renders
Acceptance: backtests
Automation: ui-web/tests/top-signals.spec.ts
Steps:
1. Open Backtests tab.
Expected:
- Table shows rows and numeric values render correctly.

### TC-BACK-V2-UI-001 Backtest v2 run view
Acceptance: backtest-run
Automation: ui-web/tests/backtest-forward-hpo.spec.ts
Steps:
1. Open Backtest v2 tab.
2. Load params and run backtest.
Expected:
- Summary metrics, equity curve, and trades are visible.

### TC-BACK-V2-UI-002 Backtest v2 parameters UX
Acceptance: frontend-params-specs
Automation: ui-web/tests/backtest-forward-hpo.spec.ts
Steps:
1. Open Backtest v2 tab.
2. Verify human-friendly labels (e.g., "Дата начала").
3. Verify allocation weights show labeled rows (e.g., "Фундаментальная").
4. Ensure technical keys (with dots) are not shown as labels.
Expected:
- Parameters are readable for humans without raw keys.
- Dict parameters render as labeled rows with numeric inputs.

### TC-FWD-UI-001 Forward status view
Acceptance: forward-status
Automation: ui-web/tests/backtest-forward-hpo.spec.ts
Steps:
1. Open Forward status tab.
2. Load status.
Expected:
- Run id/status render and last equity/trade/alert blocks are visible.

### TC-HPO-UI-001 HPO leaderboard view
Acceptance: hpo
Automation: ui-web/tests/backtest-forward-hpo.spec.ts
Steps:
1. Open HPO tab.
2. Run HPO with a search space payload.
3. (Optional) Paste a full HPO JSON request and verify it overrides the form values.
Expected:
- UI shows run_id/progress while status=running.
- Leaderboard rows render with objective/params after completion.

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
- GET /api/v2/decisions/view?limit=5
Expected:
- JSON list with decision_id, created_at, action, risk_state.
- For v2 response, rows include backend-owned `decision_ref` and `execution_ref`.
- Rows include `projection_source` (`jsonl`, `db`, or `jsonl_fallback`) for source traceability.

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

### TC-NEWS-API-001 News feed v2 contract
Acceptance: news-feed-v2
Automation: scripts/acceptance_check.py (api_list)
Request:
- GET /api/v2/news/feed?limit=5
Expected:
- JSON list response (can be empty).
- If rows exist, each row contains `news_event_id`, `published_at`, `severity`, `headline`.

### TC-PORT-API-001 Portfolio rebalance preview v2 contract
Acceptance: portfolio-rebalance-v2
Automation: scripts/acceptance_check.py (api_object)
Request:
- GET /api/v2/portfolio/rebalance/preview?limit=5
Expected:
- JSON object with `rebalance_plan_id` and `positions`.
- `positions` is an array of position proposals with entity references.

### TC-OPS-API-001 Ops health v2 contract
Acceptance: ops-health-v2
Automation: tests/test_api_v2.py
Request:
- GET /api/v2/ops/health
Expected:
- Response includes `status`, `timestamp`, `checks`.
- `checks.database.status` exists (`ok|error`).
- HTTP status is `200` for ready and `503` for degraded readiness.

### TC-OPS-API-002 Ops SLO snapshot v2 contract
Acceptance: ops-slo-v2
Automation: tests/test_api_v2.py
Request:
- GET /api/v2/ops/slo
Expected:
- Response includes `generated_at`, `slo_targets`, `api`, `events_15m`, `alerts`.
- `api` section includes metrics for `v2_signals_actions`, `v2_pretrade_check`, `v2_auto_unwind_run`.
- Alert flags are deterministic from thresholds.

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
- signal_action only `enter`/`exit`/`hold_open` (`hold_open` is used for open, not yet closed positions).
- If `signal_metrics` contains execution plan values, they are also available at top level
  (e.g., `entry_spread_pct_min`, `entry_spread_pct_max`, `tp_spread_pct_level`, `sl_spread_pct_level`).

### TC-SIG-ACT-API-002 Signal diagnostics for missing ISS orderbook
Acceptance: signals-active
Automation: tests/test_intraday_marketdata_scaling.py
Request:
- GET /api/signals/active
Expected:
- Rows expose `orderbook_stock_quote_available`, `orderbook_fut_quote_available`,
  `orderbook_stock_depth_available`, `orderbook_fut_depth_available`.
- If futures quote/depth is missing in ISS, `orderbook_data_warnings` contains
  `orderbook_fut_quote_missing` and/or `orderbook_fut_depth_missing`.

### TC-SIG-CONTRACT-API-001 Signals API contract completeness
Acceptance: signals-active, signals-history
Automation: tests/test_signal_api.py, tests/test_ui_api.py
Request:
- GET /api/signals/active
- GET /api/signals/history?limit=5
- GET /api/signals?limit=5
Expected:
- Each row contains `signal_metrics` as an object.
- Trading-plan/model keys are present both in `signal_metrics` and top-level payload.
- For legacy/incomplete rows missing values are `null`, not missing keys.

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
- 200 OK with JSON response containing `status`.
- For legged execution (`side=stock|future`) response also includes generated or passed `order_id`.

### TC-SIG-EXEC-API-002 Execute signal v1 adapter idempotency
Acceptance: signals-execute
Automation: tests/test_signal_api.py
Request:
- POST /api/signals/execute (same payload, same `idempotency_key`)
Expected:
- First request returns `status=ok`.
- Repeated request returns `status=duplicate`.
- Only one execution row is persisted for the same key.

### TC-SIG-EXEC-API-003 Fail-closed entry block in degraded/unconfirmed pretrade
Acceptance: signals-execute
Automation: tests/test_api_v2.py
Request:
- POST /api/v2/signals/{signal_id}/actions (`action=enter`) with `ui.ff_fail_closed_execution=true`.
Expected:
- API returns `409` and `status=blocked` when pretrade is not confirmed or ISS is degraded.
- No new execution row is persisted on blocked response.

### TC-SIG-POLICY-API-001 Auto-unwind policy run
Acceptance: auto-unwind-policy-v2
Automation: tests/test_api_v2.py
Request:
- POST /api/v2/policies/auto-unwind/run (`dry_run=true|false`, optional `timeout_sec`).
Expected:
- Dry run returns candidates and counters without persistence.
- Execute mode creates idempotent `exit` actions for stale leg imbalance candidates.

### TC-PRETRADE-API-001 Pre-trade check endpoint
Acceptance: pretrade-check
Automation: tests/test_ui_api.py
Request:
- GET /api/pretrade/check?stock=...&future=...&snapshots=1&min_hits=1&poll_sec=0
Expected:
- JSON object contains `status`, `ready_to_place`, `reasons`.
- Response includes `order_price_bands`, `volume_requirements`, `gates`, and `hits`.

### TC-PRETRADE-API-002 Strict quote gate behavior
Acceptance: pretrade-check
Automation: tests/test_pretrade_delay_gate.py
Request:
- Call delay-gate flow with missing futures bid/ask.
Expected:
- Placement is blocked with `fut_quote_missing` regardless of tradeflow fallback settings.

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

### TC-HPO-API-001 HPO run (async start)
Acceptance: hpo
Automation: scripts/acceptance_check.py (post_json)
Request:
- POST /api/hpo/run
Expected:
- Response includes run_id and status=running.
- When `optimization.metric` and `optimization.mode` are provided, objective direction matches the mode.

### TC-HPO-API-002 HPO status
Acceptance: hpo-status
Automation: scripts/acceptance_check.py (http_status)
Request:
- GET /api/hpo/status
Expected:
- 200 OK after an HPO run is started.


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
