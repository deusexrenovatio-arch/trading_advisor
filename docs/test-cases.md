# Test Suite - Acceptance Coverage

## Purpose
- One place to run manual QA and see automated coverage.
- Each acceptance scenario is linked to one or more test cases.

## Preconditions
- Backend: http://127.0.0.1:8050
- Frontend: http://127.0.0.1:5176
- Data: signal history has at least one day with known stock/future/action.

## Acceptance Mapping (scenario -> test cases)
- dev-skill-start-gate -> TC-DEV-WF-001
- dev-skill-recheck-gate -> TC-DEV-WF-002
- dev-skill-prepush-gate -> TC-DEV-WF-003
- first-time-right-goal-contract-gate -> TC-FTR-PROC-001
- first-time-right-user-case-gate -> TC-FTR-PROC-002
- first-time-right-budget-stop-gate -> TC-FTR-PROC-003
- first-time-right-load-readiness-gate -> TC-FTR-PROC-004
- first-time-right-context-integrity-gate -> TC-FTR-PROC-005
- first-time-right-repeated-issue-gate -> TC-FTR-PROC-006
- process-telemetry-start-first-patch -> TC-PROC-TELE-001
- process-task-outcome-closeout -> TC-PROC-TELE-002
- process-repeated-signature-prevention -> TC-PROC-TELE-003
- process-regression-burn-in-thresholds -> TC-PROC-TELE-004
- process-regression-acknowledged-debt -> TC-PROC-TELE-005
- process-regression-worsening-after-ack -> TC-PROC-TELE-006
- decision-view -> TC-DEC-API-001, TC-DEC-UI-001
- decision-view-filters -> TC-DEC-API-005
- decision-view-aggregation -> TC-DEC-API-002
- decision-log-aggregation -> TC-DEC-API-003
- decision-action -> TC-DEC-API-004, TC-DEC-UI-002
- params-specs -> TC-PARAMS-API-001
- frontend-params-specs -> TC-BACK-V2-UI-001, TC-BACK-V2-UI-002
- top-pairs -> TC-TOP-API-001, TC-TOP-API-002, TC-TOP-UI-001, TC-TOP-UI-002, TC-TOP-UI-003, TC-TOP-UI-004
- signals-active -> TC-SIG-ACT-API-001, TC-SIG-ACT-API-002, TC-SIG-CONTRACT-API-001, TC-SIG-ACT-UI-001, TC-SIG-PLAN-UI-001, TC-SIG-UI-WORKFLOW-001, TC-TG-UI-002, TC-TG-UI-003, TC-TG-WRK-002, TC-TG-WRK-003
- signals-action-v2 -> TC-SIG-ACT-API-003
- signals-history -> TC-SIG-HIST-API-001, TC-SIG-HIST-API-003, TC-SIG-CONTRACT-API-001, TC-SIG-HIST-UI-001, TC-SIG-HIST-UI-002
- signals-history-reasons -> TC-SIG-HIST-API-004
- signals-execute -> TC-SIG-EXEC-API-001, TC-SIG-EXEC-API-002, TC-SIG-EXEC-API-003, TC-SIG-EXEC-UI-001, TC-SIG-EXEC-UI-002
- signals-ack-execute -> TC-SIG-ACK-API-001, TC-SIG-ACK-UI-001, TC-TG-UI-001, TC-TG-WRK-001, TC-TG-WRK-004
- auto-unwind-policy-v2 -> TC-SIG-POLICY-API-001
- pretrade-check -> TC-PRETRADE-API-001, TC-PRETRADE-API-002, TC-PRETRADE-UI-001
- signals-history-range -> TC-SIG-HIST-API-002, TC-SIG-HIST-UI-001
- backtests -> TC-BACK-API-001, TC-BACK-UI-001
- backtest-run -> TC-BACK-V2-API-001, TC-BACK-V2-API-002
- spread-series -> TC-SPREAD-API-001, TC-SPREAD-UI-001, TC-SPREAD-UI-002
- forward-start -> TC-FWD-API-001
- forward-status -> TC-FWD-API-002
- frontend -> TC-FE-HTTP-001
- frontend-proxy -> TC-FE-PROXY-001
- unified-minute-runtime -> TC-UNI-API-001, TC-UNI-API-002, TC-UNI-API-003, TC-PERF-GATE-MAN-001, TC-PERF-ARCH-UNIT-001
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
- US-04 Enter a position -> signals-action-v2 + signals-execute + pretrade-check + decision-action (TC-SIG-ACT-API-003, TC-SIG-EXEC-API-001, TC-SIG-EXEC-API-002, TC-SIG-EXEC-UI-001, TC-SIG-EXEC-UI-002, TC-PRETRADE-API-001, TC-PRETRADE-UI-001, TC-DEC-API-004, TC-DEC-UI-002).
- US-04 Enter a position -> fail-closed guard on degraded/pretrade-unknown entry (tests/test_api_v2.py).
- US-05 Early exit (alpha) -> signals-history-reasons + spread-series (TC-SIG-HIST-API-004, TC-SPREAD-API-001) + unit tests: tests/test_spread_carry_alpha.py.
- US-06 Hold to expiry or roll -> signals-history-reasons + spread-series (TC-SIG-HIST-API-004, TC-SPREAD-API-001) + unit tests: tests/test_spread_carry_alpha.py.
- US-07 Backtest review -> backtests (TC-BACK-API-001, TC-BACK-UI-001).
- US-08 Risk/liquidity rejection -> top-pairs + unit checks (TC-TOP-API-001, TC-TOP-UI-001; tests/test_liquidity_metrics.py, tests/test_risk_gate.py).
- US-09 Forward paper daily cycle -> forward-start/forward-status (TC-FWD-API-001, TC-FWD-API-002) + unit tests: tests/test_forward_engine.py.
- US-10 HPO run + leaderboard -> hpo, hpo-status (TC-HPO-API-001, TC-HPO-API-002, TC-HPO-UNIT-001) + unit tests: tests/hpo/test_folds.py, tests/hpo/test_objective.py, tests/hpo/test_leaderboard.py.
- US-11 Review decisions with server filters -> decision-view, decision-view-filters (TC-DEC-API-001, TC-DEC-API-005, TC-DEC-UI-001).
- US-12 Confirm signal review from Telegram -> signals-ack-execute + signals-active (TC-SIG-ACK-API-001, TC-SIG-ACK-UI-001, TC-SIG-ACT-API-001, TC-TG-UI-001, TC-TG-WRK-001, TC-TG-WRK-004, TC-TG-WRK-010, TC-TG-WRK-011).
- US-13 Morning bot liveness check -> signals-active (TC-TG-UI-002, TC-TG-UI-003, TC-TG-WRK-002, TC-TG-WRK-003).
- US-14 Complete user-facing flow without hidden gaps -> first-time-right-user-case-gate + signals-active + pretrade-check + signals-execute (TC-FTR-PROC-002, TC-SIG-UI-WORKFLOW-001, TC-PRETRADE-UI-001, TC-SIG-EXEC-UI-001).
- US-15 Fast convergence to target metrics -> first-time-right-goal-contract-gate + hpo/hpo-status (TC-FTR-PROC-001, TC-HPO-API-001, TC-HPO-API-002).
- US-16 Long operations are visible and interruptible -> first-time-right-budget-stop-gate (TC-FTR-PROC-003).
- US-17 Heavy workloads run with load-ready design -> first-time-right-load-readiness-gate + unified-minute-runtime (TC-FTR-PROC-004, TC-PERF-ARCH-UNIT-001, TC-PERF-GATE-MAN-001).
- US-18 Repeated issues escalate to root-cause review -> first-time-right-repeated-issue-gate (TC-FTR-PROC-006).

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

### TC-SPREAD-UI-002 Spread chart supports timeframe switch
Acceptance: spread-series
Automation: ui-web/tests/top-signals.spec.ts
Steps:
1. Open Top pairs and expand row details.
2. Switch chart timeframe between `1H`, `5m`, and `1D`.
Expected:
- Candle chart updates without errors for each interval.
- Active interval button reflects selected timeframe.

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

### TC-SIG-ACK-UI-001 Telegram review lifecycle
Acceptance: signals-ack-execute, signals-active
Automation: manual
Steps:
1. Start backend and `telegram_bot` worker.
2. Send `/start` to bot from whitelisted user.
3. Wait for a signal message and click `Mark viewed`.
4. Open Signals tab in UI and reload data.
Expected:
- Signal row shows `signal_viewed=true`.
- `signal_details_pending=true` until first `enter_filled` or `entry_cancelled` execution is logged for the pair.
- Review action does not change open-position balance fields.

### TC-TG-UI-001 Telegram onboarding and access control
Acceptance: signals-ack-execute
Automation: manual
Steps:
1. Start backend and `telegram_bot` worker with a whitelist containing only user `A`.
2. From user `B` send `/start`.
3. From user `A` send `/start` and `/help`.
Expected:
- User `B` receives access denied message and is not added to worker state.
- User `A` receives onboarding and help text.
- Worker state contains `registered_chats` for whitelisted users only.

### TC-TG-UI-002 Daily heartbeat happy path
Acceptance: signals-active
Automation: manual
Steps:
1. Configure `daily_healthcheck_enabled=true` and `daily_healthcheck_time_local` a few minutes ahead.
2. Ensure backend `/api/signals/active` responds.
3. Wait for scheduled local time.
Expected:
- Bot sends one morning heartbeat message.
- Message includes bot online status, backend status `OK`, and active signals count.
- Repeated worker cycles on the same day do not produce duplicate heartbeat messages.

### TC-TG-UI-003 Daily heartbeat with backend outage
Acceptance: signals-active
Automation: manual
Steps:
1. Configure daily heartbeat as in TC-TG-UI-002.
2. Stop backend before heartbeat time.
3. Wait for scheduled local time.
Expected:
- Bot still sends heartbeat message.
- Message contains `Backend: ERROR` and states that data check failed.

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
- GET /api/v2/decisions/view?limit=5
- GET /api/decision-view?limit=5 (adapter compatibility smoke)
Expected:
- JSON list with decision_id, created_at, action, risk_state.
- For v2 response, rows include backend-owned `decision_ref` and `execution_ref`.
- Rows include `projection_source` (`jsonl`, `db`, or `jsonl_fallback`) for source traceability.

### TC-DEC-API-002 Decision view aggregation field
Acceptance: decision-view-aggregation
Automation: scripts/acceptance_check.py (decision-view-aggregation)
Request:
- GET /api/v2/decisions/view?limit=1
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
- POST /api/v2/decisions/{decision_id}/actions
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
- GET /api/v2/top-pairs?limit=5
Expected:
- Required keys include spread_pct, rtc_pct, floor_rate_annual, score_floor, total_score, decision.
- signal_reasons/signal_metrics are absent.

### TC-TOP-API-002 Top pairs score gate compatibility
Acceptance: top-pairs
Automation: tests/test_ui_api.py
Request:
- GET /api/v2/top-pairs?limit=5&require_score_gate=true
Expected:
- Response remains JSON-compatible for UI tables.
- For non-empty rows, score-related keys (`score_gate_pass`, `score_exec_probability`, `score_earn_probability`) are present.

### TC-SIG-ACT-API-001 Active signals actionable
Acceptance: signals-active
Automation: scripts/acceptance_check.py (signals-active)
Request:
- GET /api/v2/signals/active
Expected:
- signal_action only `enter`/`exit`/`hold_open` (`hold_open` is used for open, not yet closed positions).
- If `signal_metrics` contains execution plan values, they are also available at top level
  (e.g., `entry_spread_pct_min`, `entry_spread_pct_max`, `tp_spread_pct_level`, `sl_spread_pct_level`).
- Response includes Telegram usage flags: `signal_used`, `signal_used_at`, `signal_used_by`, `signal_details_pending`.

### TC-SIG-ACT-API-002 Signal diagnostics for missing ISS orderbook
Acceptance: signals-active
Automation: tests/test_intraday_marketdata_scaling.py
Request:
- GET /api/v2/signals/active
Expected:
- Rows expose `orderbook_stock_quote_available`, `orderbook_fut_quote_available`,
  `orderbook_stock_depth_available`, `orderbook_fut_depth_available`.
- If futures quote/depth is missing in ISS, `orderbook_data_warnings` contains
  `orderbook_fut_quote_missing` and/or `orderbook_fut_depth_missing`.

### TC-SIG-ACT-API-003 Signal action v2 from active feed
Acceptance: signals-action-v2
Automation: scripts/acceptance_check.py (signal_action)
Request:
- GET /api/v2/signals/active?limit=5 (resolve `signal_id`)
- POST /api/v2/signals/{signal_id}/actions (`action=mark_viewed`)
Expected:
- If active rows exist, action request returns HTTP 200 with status `ok` or `duplicate`.
- Response includes `signal_id`, `entity_ref`, `action`, and `fail_closed`.
- Scenario is skipped (not failed) when no active rows are available.

### TC-SIG-CONTRACT-API-001 Signals API contract completeness
Acceptance: signals-active, signals-history
Automation: tests/test_signal_api.py, tests/test_ui_api.py
Request:
- GET /api/v2/signals/active
- GET /api/v2/signals/history?limit=5
- GET /api/signals?limit=5
Expected:
- Each row contains `signal_metrics` as an object.
- Trading-plan/model keys are present both in `signal_metrics` and top-level payload.
- For legacy/incomplete rows missing values are `null`, not missing keys.

### TC-SIG-HIST-API-001 History list and allowed actions
Acceptance: signals-history
Automation: scripts/acceptance_check.py (signals-history)
Request:
- GET /api/v2/signals/history?limit=5
Expected:
- Required keys exist, action in enter/exit/hold.

### TC-SIG-HIST-API-002 Date range inclusive
Acceptance: signals-history-range
Automation: scripts/acceptance_check.py (signals-history-range)
Request:
- GET /api/v2/signals/history?from=YYYY-MM-DD&to=YYYY-MM-DD
Expected:
- Inclusive range for the day.

### TC-SIG-HIST-API-003 Filter by stock/future/action
Acceptance: signals-history
Automation: tests/test_signal_api.py
Request:
- GET /api/v2/signals/history?stock=SBER&future=SRH6&signal_action=enter&limit=500
Expected:
- All rows match stock/future/action.

### TC-SIG-HIST-API-004 Signal reasons and metrics present
Acceptance: signals-history-reasons
Automation: scripts/acceptance_check.py (api_list)
Request:
- GET /api/v2/signals/history?limit=5
Expected:
- Each row includes signal_reasons and signal_metrics.

### TC-SIG-EXEC-API-001 Execute signal endpoint
Acceptance: signals-execute
Automation: scripts/acceptance_check.py (signal_action)
Request:
- GET /api/v2/signals/active?limit=5 (resolve `signal_id`)
- POST /api/v2/signals/{signal_id}/actions (`action=enter`)
Expected:
- Action response contains `status`, `signal_id`, `entity_ref`, and `fail_closed`.
- Allowed outcomes for smoke: `ok`, `duplicate`, or `blocked` (with reason fields).
- Scenario is skipped (not failed) when no active rows are available.

### TC-SIG-EXEC-API-002 Execute signal v1 adapter idempotency
Acceptance: signals-execute
Automation: tests/test_signal_api.py
Request:
- POST /api/signals/execute (same payload, same `idempotency_key`)
Expected:
- First request returns `status=ok`.
- Repeated request returns `status=duplicate`.
- Only one execution row is persisted for the same key.
- Compatibility target: keep v1 adapter stable for transition period while v2 is primary.

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

### TC-SIG-ACK-API-001 Execute Telegram review compatibility endpoint
Acceptance: signals-ack-execute
Automation: scripts/acceptance_check.py (post_json)
Request:
- POST /api/signals/execute with `action=ack`
Expected:
- 200 OK with JSON response containing `status`.
- Compatibility alias is accepted, but canonical stored action is `mark_viewed`.
- Default stored status is `viewed` when status is omitted.

### TC-TG-WRK-001 Whitelist registration in worker
Acceptance: signals-ack-execute
Automation: tests/test_telegram_worker.py::test_worker_registers_only_whitelisted_users
Request:
- Simulate `/start` updates from both non-whitelisted and whitelisted users.
Expected:
- Worker keeps only whitelisted users in `registered_chats`.
- Worker sends access denied response to non-whitelisted users.

### TC-TG-WRK-002 Daily heartbeat once per local day
Acceptance: signals-active
Automation: tests/test_telegram_worker.py::test_worker_daily_healthcheck_sent_once_per_day
Request:
- Trigger `_send_daily_healthcheck()` twice in one day for registered chat.
Expected:
- Exactly one heartbeat message is sent.
- Worker stores sent date in `daily_healthcheck_last_sent_date_by_chat`.

### TC-TG-WRK-003 Daily heartbeat backend error fallback
Acceptance: signals-active
Automation: tests/test_telegram_worker.py::test_worker_daily_healthcheck_reports_backend_error
Request:
- Trigger `_send_daily_healthcheck()` with backend session raising connection error.
Expected:
- Heartbeat message is still sent.
- Message contains `Backend: ERROR`.

### TC-TG-WRK-004 Expired Telegram review token is rejected
Acceptance: signals-ack-execute
Automation: tests/test_telegram_worker.py::test_worker_callback_rejects_expired_token
Request:
- Process callback with expired `ack:<token>`.
Expected:
- No review execution call is sent to backend.
- Callback token is removed from worker state and user receives rejection notice.

### TC-TG-WRK-005 Worker deduplicates stable enter fingerprint
Acceptance: signals-active
Automation: tests/test_telegram_worker.py::test_worker_uses_signal_fingerprint_from_api_for_enter_dedup
Request:
- Return two active batches with different `run_id` but same `signal_fingerprint` for `enter`.
Expected:
- Worker sends only one message.
- Pending callback state stores single fingerprint.

### TC-TG-WRK-006 Worker notifies once when sent enter goes out of range
Acceptance: signals-active
Automation: tests/test_telegram_worker.py::test_worker_notifies_once_when_sent_enter_goes_out_of_range
Request:
- First batch: in-range `enter`.
- Next batches: same fingerprint with current prices outside original corridor.
Expected:
- Worker sends initial signal message plus exactly one out-of-range update.
- No duplicate out-of-range spam for repeated out-of-range batches.

### TC-TG-WRK-007 Pair-level cooldown blocks rapid new enter fingerprints
Acceptance: signals-active
Automation: tests/test_telegram_worker.py::test_worker_throttles_new_enter_fingerprints_per_pair
Request:
- Two consecutive `enter` signals for same pair with different fingerprints inside cooldown window.
Expected:
- Worker sends only the first one.

### TC-TG-WRK-008 Worker prefers pair actionability endpoint
Acceptance: signals-actionability
Automation: tests/test_telegram_worker.py::test_worker_prefers_pair_actionability_endpoint
Request:
- Start worker and run one broadcast cycle.
Expected:
- First backend call goes to `/api/v2/pairs/actionability` with fallback chain only on failure.

### TC-TG-WRK-009 Stale intent callback is closed with user-facing hint
Acceptance: signals-actionability
Automation: tests/test_telegram_worker.py::test_worker_callback_marks_stale_intent_and_drops_token
Request:
- Process callback where backend rejects `mark_viewed` with `message=intent_superseded_or_stale`.
Expected:
- Token is removed from pending callbacks.
- User receives explicit stale-intent hint instead of generic failure.

### TC-TG-WRK-010 Telegram H4A follow-up broadcasts post-fill stages
Acceptance: signals-actionability
Automation: tests/test_telegram_worker.py::test_worker_sends_post_fill_break_even_and_time_stop_followups
Request:
- Return one `enter_filled` H4A row with post-fill packet, break-even/trailing trigger, and time-stop reminder due.
Expected:
- Worker sends dedicated follow-up messages for post-fill packet, break-even/trailing, and time stop.
- Each follow-up message exposes `Confirm` and `Manual override` callbacks.

### TC-TG-WRK-011 Telegram H4A follow-up confirmation is persisted without lifecycle drift
Acceptance: signals-actionability
Automation: tests/test_telegram_worker.py::test_worker_callback_confirm_followup_posts_stage_payload
Request:
- Process callback `act:confirm_followup:<token>` for an H4A follow-up stage.
Expected:
- Backend receives `action=confirm_followup` with `h4a_stage`.
- Operator status remains on the current execution lifecycle and does not regress to entry-consumption semantics.

### TC-SIG-ACT-API-004 v2 active row exposes delivery contract fields
Acceptance: signals-active
Automation: tests/test_signal_api.py::test_signals_active_v2_exposes_delivery_fields
Request:
- GET `/api/v2/signals/active` for row with `enter` action.
Expected:
- Row includes `delivery_action`, `delivery_allowed`, `delivery_suppressed_reason`, `entry_signal_expired`, `entry_range_eligible`.

### TC-SIG-ACT-API-005 Pending enter promotion for open/flat hold states
Acceptance: signals-active
Automation:
- tests/test_signal_api.py::test_signals_active_promotes_hold_open_to_pending_enter
- tests/test_signal_api.py::test_signals_active_promotes_flat_hold_to_pending_enter
Request:
- Latest run has `hold`, recent history has unused `enter` intent for same pair.
Expected:
- Active row is promoted to actionable `enter`.
- Origin references (`signal_origin_run_id`, `signal_origin_timestamp`) point to promoted intent.

### TC-SIG-ACT-API-006 Pending enter promotion stops after explicit use
Acceptance: signals-active
Automation:
- tests/test_signal_api.py::test_signals_active_pending_enter_stops_after_explicit_use
- tests/test_signal_api.py::test_signals_active_flat_pending_enter_stops_after_explicit_use
Request:
- Same as pending promotion case, plus explicit usage action for the promoted fingerprint.
Expected:
- Row is not promoted to `enter` anymore and remains `hold_open`/non-actionable equivalent.

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
- Acceptance smoke skips this case when pair source is unavailable (`/api/v2/top-pairs` is empty).

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
- Scenario is skipped (not failed) when top-pairs source is empty in the runtime dataset.

### TC-UNI-API-001 Unified runtime top-pairs compatibility
Acceptance: unified-minute-runtime
Automation: tests/test_ui_api.py
Request:
- GET /api/top-pairs?limit=5
Expected:
- Response remains compatible with legacy UI consumers.
- Rows include `stock`, `future`, `signal_action`, `signal_score` when data is available.

### TC-UNI-API-002 Unified runtime signals compatibility
Acceptance: unified-minute-runtime
Automation: tests/test_signal_api.py
Request:
- GET /api/signals?limit=5
Expected:
- Endpoint response keeps legacy field compatibility for consumers using v1 routes.

### TC-UNI-API-003 Unified runtime backtests compatibility
Acceptance: unified-minute-runtime
Automation: tests/test_ui_api.py
Request:
- GET /api/backtests?limit=5
Expected:
- Backtest list remains available and JSON-compatible after minute-runtime integration.

### TC-FWD-API-001 Forward start
Acceptance: forward-start
Automation: tests/test_backtest_forward_api.py
Request:
- POST /api/forward/start
Expected:
- Response includes run_id and state payload.
- Acceptance smoke may skip with `400 Missing raw data` when `data/raw/shares.csv` and `data/raw/futures.csv` are absent in the runtime dataset.

### TC-FWD-API-002 Forward status
Acceptance: forward-status
Automation: tests/test_backtest_forward_api.py
Request:
- GET /api/forward/status
Expected:
- Response includes run_id and last known state.
- Acceptance smoke may skip with `400 no_active_run` if forward run has not been started in the current runtime dataset.

### TC-HPO-API-001 HPO run (async start)
Acceptance: hpo
Automation: scripts/acceptance_check.py (post_json)
Request:
- POST /api/hpo/run
Expected:
- Response includes run_id and status=running.
- When `optimization.metric` and `optimization.mode` are provided, objective direction matches the mode.
- Acceptance smoke may skip with `400 Missing raw data` when required raw datasets are absent.

### TC-HPO-API-002 HPO status
Acceptance: hpo-status
Automation: scripts/acceptance_check.py (http_status)
Request:
- GET /api/hpo/status
Expected:
- 200 OK after an HPO run is started.
- Acceptance smoke may skip with `400 no_active_run` if no HPO run exists in the runtime dataset.


### TC-FE-PROXY-001 Vite proxy API
Acceptance: frontend-proxy
Automation: scripts/acceptance_check.py (frontend-proxy)
Request:
- GET http://127.0.0.1:5176/api/v2/top-pairs?limit=5
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
- Constraint violations yield an invalid-objective sentinel for objective mode.
- Leaderboard orders by objective and best_config matches the top trial.

### TC-PERF-GATE-MAN-001 Manual performance gate checklist
Acceptance: unified-minute-runtime
Automation: manual
Steps:
1. Run minute-runtime compute in cold mode and warm mode.
2. Capture hardware profile and cache mode in the report.
Expected:
- Cold/warm results are recorded separately.
- No regression beyond approved threshold versus baseline.

### TC-PERF-ARCH-UNIT-001 Runtime architecture/perf unit checks
Acceptance: unified-minute-runtime
Automation: tests/perf/*
Steps:
1. Run targeted performance unit suite for minute-runtime components.
Expected:
- Runtime modules pass architecture/performance guards used by CI.

## Process and Workflow Test Cases

### TC-DEV-WF-001 Start phase invokes mandatory bootstrap skill
Acceptance: dev-skill-start-gate
Automation: manual
Steps:
1. Start a new development stream (new branch/worktree).
2. Verify `parallel-worktree-flow` is invoked before implementation.
3. Verify domain flow skill is selected (`trading-ui-dashboard`, `ml-backtest-hpo-lab`, or strategy flow).
Expected:
- Start of development always begins with bootstrap skill.
- Domain work starts only after flow skill selection.

### TC-DEV-WF-002 Recheck phase reruns flow verification skills
Acceptance: dev-skill-recheck-gate
Automation: manual
Steps:
1. Apply a fix in an active stream.
2. Rerun flow verification skill (`frontend-behavior-check`, `ml-backtest-hpo-lab`, or strategy gates).
3. Run required checks listed in `docs/DEV_WORKFLOW.md`.
Expected:
- Recheck includes both skill-level validation and required workflow checks.
- Task is not closed if any required check fails.

### TC-DEV-WF-003 Pre-push phase enforces blocker checks
Acceptance: dev-skill-prepush-gate
Automation: manual
Steps:
1. Before push, run all required checks from `docs/DEV_WORKFLOW.md`.
2. Verify failures are treated as blockers.
3. Push only after all checks pass.
Expected:
- Pre-push gate is deterministic and repeatable.
- No push is performed with failed required checks.

### TC-FTR-PROC-001 Goal contract is explicit before implementation
Acceptance: first-time-right-goal-contract-gate
Automation: manual
Steps:
1. Start a non-trivial task (research or user-facing logic).
2. Record user outcome, acceptance criteria, out-of-scope, and assumptions.
3. Confirm implementation starts only after contract is explicit.
Expected:
- Goal contract is written before coding.
- Ambiguous target blocks implementation start.

### TC-FTR-PROC-002 User-case completeness is verified before coding
Acceptance: first-time-right-user-case-gate
Automation: manual
Steps:
1. For the active task, list primary flow.
2. List edge, negative, interruption/retry, and stale/partial data flows.
3. Confirm missing scenarios are treated as blockers.
Expected:
- Scenario inventory is explicit and covers non-happy paths.
- Implementation does not proceed with uncovered critical scenarios.

### TC-FTR-PROC-003 Runtime budget and stop/replan controls are defined
Acceptance: first-time-right-budget-stop-gate
Automation: manual
Steps:
1. Before long command/compute, define runtime and network budget.
2. Define stop/replan trigger and checkpoint cadence.
3. Execute smoke-first run before full scale.
Expected:
- Long-running operations have ETA, checkpoints, and stop trigger.
- Trigger breach leads to replanning instead of blind continuation.

### TC-FTR-PROC-004 High-load readiness is designed before heavy runs
Acceptance: first-time-right-load-readiness-gate
Automation: manual
Steps:
1. For heavy task (HPO/export/inference), define chunking strategy.
2. Define parallel limits and cache/resume path.
3. Confirm fallback behavior for degraded runtime.
Expected:
- Heavy workload plan includes chunking, bounded parallelism, and resume.
- Execution is not started without load-readiness plan.

### TC-FTR-PROC-005 Context integrity is enforced against main objective
Acceptance: first-time-right-context-integrity-gate
Automation: manual
Steps:
1. Review planned changes for active task.
2. Map each change to main user objective.
3. Defer side-path work without direct user value.
Expected:
- Change list remains aligned with main objective.
- Context drift is detected and corrected before implementation.

### TC-FTR-PROC-006 Repeated issue escalates to root-cause review
Acceptance: first-time-right-repeated-issue-gate
Automation: manual
Steps:
1. Detect repeated failure/regression for same problem.
2. Produce findings + hypotheses + fix plan before next patch.
3. Run regression checklist after fix.
Expected:
- Team switches from patching to structured root-cause workflow.
- Issue is not closed without explicit regression validation.

### TC-PROC-TELE-001 Worktree start and lean gate first patch emit telemetry lifecycle
Acceptance: process-telemetry-start-first-patch
Automation: tests/test_task_outcomes.py::test_run_lean_gate_records_first_patch_in_minimal_repo
Steps:
1. Start task with `worktree_guard -Action Check`.
2. Make one first diff on the task path.
3. Run `python scripts/run_lean_gate.py`.
Expected:
- `.runlogs/agent-process/task-events.jsonl` contains `task_start` and `first_patch`.
- `.runlogs/agent-process/state.json` stores active task id and time-to-first-patch.

### TC-PROC-TELE-002 Non-trivial diff requires task outcome sync and ledger record
Acceptance: process-task-outcome-closeout
Automation: tests/test_task_outcomes.py::test_validate_task_outcomes_requires_sync_for_non_trivial_diff
Steps:
1. Create a non-trivial working-tree diff.
2. Run `python scripts/validate_task_outcomes.py` before syncing.
3. Run `python scripts/sync_task_outcomes.py` and validate again.
Expected:
- Validator fails before sync because current task has no ledger record.
- Validator passes after sync and `memory/task_outcomes.yaml` contains the active task id.

### TC-PROC-TELE-003 Repeated incident signature needs new prevention artifact
Acceptance: process-repeated-signature-prevention
Automation: tests/test_task_outcomes.py::test_validate_task_outcomes_blocks_repeated_signature_without_new_artifact
Steps:
1. Seed ledger with an older outcome for one `incident_signature`.
2. Close a new task with the same signature and the same prevention artifact.
3. Run `python scripts/validate_task_outcomes.py`.
Expected:
- Validation fails until the new task uses a distinct improvement artifact and linked follow-up.

### TC-PROC-TELE-004 Burn-in keeps rolling regressions advisory until 20 completed tasks
Acceptance: process-regression-burn-in-thresholds
Automation: tests/test_agent_process_telemetry.py::test_rollup_respects_burn_in_and_thresholds
Steps:
1. Compute rollup with fewer than 20 completed tasks.
2. Compute rollup again with 20 tasks and poor metrics.
Expected:
- Burn-in window does not block before 20 completed tasks.
- Threshold status flips to blocking once the 20-task window exists and metrics regress.

### TC-PROC-TELE-005 Acknowledged baseline debt stays non-blocking under active remediation
Acceptance: process-regression-acknowledged-debt
Automation: tests/test_agent_process_telemetry.py::test_validate_process_regressions_allows_acknowledged_baseline_debt
Steps:
1. Seed 20 completed tasks with weak decision-quality and context-efficiency metrics.
2. Keep an active remediation plan for the known baseline debt.
3. Run `python scripts/validate_process_regressions.py`.
Expected:
- Validator returns success.
- Failing dimensions are marked as `acknowledged_debt`, not `fail`.
- Blocking remains false while the debt is tracked and does not worsen.

### TC-PROC-TELE-006 Worsening after acknowledgement becomes blocking again
Acceptance: process-regression-worsening-after-ack
Automation: tests/test_agent_process_telemetry.py::test_validate_process_regressions_blocks_worsening_acknowledged_debt
Steps:
1. Seed one full baseline window with acknowledged weak metrics.
2. Seed the next full window with worse decision-quality and context-efficiency values.
3. Run `python scripts/validate_process_regressions.py`.
Expected:
- Validator fails again.
- The worsening dimensions are marked as `regressed`.
- The gate does not allow acknowledged debt to hide a fresh degradation.

## Regression Checklist (minimum)
- /api/v2/signals/history returns JSON (no HTML).
- Signals tab loads and renders history table.
- Filters change visible rows (not just the first row).

## Mapping validation
- Run `python scripts/validate_test_cases.py` to ensure acceptance scenarios reference real test cases.
- Run `python scripts/validate_user_needs_catalog.py` to ensure user needs/use-cases map to acceptance scenarios and test cases with full acceptance coverage.

## Planned Pair-Centric Cases (Migration)

### TC-PAIR-ACT-API-001 Pair actionability feed returns usable-now projection
Preconditions:
- Backend has fresh signal cycle and market snapshot.
Steps:
1. GET `/api/v2/pairs/actionability`.
Expected:
- Each row has `pair_id`, `intent`, `entry_plan`, `entry_range_now`, `delivery`.
- `actionability_state` is one of `actionable_enter|actionable_exit|hold_open|blocked_entry|inactive`.
- `hold_required=true` only when execution ledger indicates open position.

### TC-PAIR-ACT-API-002 Out-of-range lifecycle is explicit and reversible
Preconditions:
- Pair has actionable enter and sent Telegram fingerprint.
Steps:
1. Move current prices out of planned corridor.
2. GET `/api/v2/pairs/actionability`.
3. Move prices back into recomputed executable bounds.
4. GET `/api/v2/pairs/actionability` again.
Expected:
- First response shows `intent.status=out_of_range` and non-actionable entry.
- Second response shows new executable revision (`intent_id` changed) and actionable enter restored.

### TC-PAIR-ACT-API-003 Pair action endpoint is idempotent
Preconditions:
- At least one row from `/api/v2/pairs/actionability`.
Steps:
1. POST `/api/v2/pairs/{pair_id}/actions` with `action=mark_viewed`, fixed `idempotency_key`.
2. Repeat same request with same key.
Expected:
- First response `status=ok`.
- Second response `status=duplicate`.

### TC-PAIR-ACT-TG-001 Telegram sends one out-of-range update per fingerprint
Preconditions:
- Telegram worker uses pair-centric endpoint.
Steps:
1. Send enter notification for fingerprint A.
2. Keep prices out-of-range for multiple polling cycles.
Expected:
- Exactly one out-of-range update for fingerprint A.
- No repeated out-of-range messages while fingerprint A stays unchanged.

### TC-ENTITY-ACT-API-001 Canonical actionability feed supports pair and instrument
Preconditions:
- Backend has at least one pair signal and one instrument signal in current snapshot.
Steps:
1. GET `/api/v2/signals/actionability`.
2. Filter rows by `entity_ref.entity_type`.
Expected:
- Feed contains rows for both `pair` and `instrument`.
- Common fields (`intent`, `delivery`, `actionability_state`, `policy_outcome`) are present for both.

### TC-ENTITY-ACT-API-002 Conflicting evidence blocks entry deterministically
Preconditions:
- Entity has mixed sources: support from technical/fundamental and high-severity opposing news.
Steps:
1. GET `/api/v2/signals/actionability` for entity.
Expected:
- `evidence_summary.conflict_score` is non-zero.
- `evidence_summary.veto_active=true`.
- `policy_outcome.status=block` and delivery is suppressed with explicit reason.

### TC-ENTITY-ACT-API-003 Entity action endpoint idempotency and fail-closed
Automation: tests/test_api_v2.py::test_v2_entity_and_pair_actions_endpoints_are_idempotent
Preconditions:
- Entity row exists in canonical actionability feed.
Steps:
1. POST `/api/v2/entities/{entity_type}/{entity_id}/signals/actions` with fixed `idempotency_key`.
2. Repeat request with same key.
Expected:
- First response status is `ok`.
- Second response status is `duplicate`.
- Response contains `entity_ref`, `action`, `fail_closed`.

### TC-ENTITY-ACT-API-004 Policy precedence applies deterministic gate order
Preconditions:
- Entity has gate trace with at least one `reduce` and one `review` event from different gates.
Steps:
1. GET `/api/v2/signals/actionability` for entity.
Expected:
- `policy_outcome.precedence_version` is present.
- Final `policy_outcome.status` follows precedence (`review` dominates `reduce`; `block` dominates all).
- `policy_outcome.gate_trace` exposes gate priorities and reason codes.

### TC-ENTITY-ACT-API-005 Review state remains visible and non-auto-delivered
Preconditions:
- Entity resolves to `policy_outcome.status=review`.
Steps:
1. GET `/api/v2/signals/actionability` for entity.
Expected:
- `actionability_state=review_entry`.
- Row is visible in feed.
- Enter delivery is suppressed or marked for manual review only.

### TC-ENTITY-ACT-API-006 Open-position overlay does not hide fresh enter intent
Preconditions:
- Entity has `position_state=open` from execution ledger and a new active in-range enter intent.
Steps:
1. GET `/api/v2/signals/actionability` for entity.
Expected:
- Row contains open-position overlay (`hold_open` semantics via axes/flags).
- Fresh enter intent remains visible and traceable (not silently suppressed by hold state).

### TC-ENTITY-ACT-API-007 mark_viewed keeps intent actionable without changing position state
Automation: tests/test_api_v2.py::test_v2_pair_ack_alias_marks_signal_as_viewed_without_consuming_intent
Preconditions:
- Active entity intent exists and position is flat.
Steps:
1. POST `/api/v2/entities/{entity_type}/{entity_id}/signals/actions` with `action=mark_viewed`.
2. GET `/api/v2/signals/actionability` for same entity.
Expected:
- Intent state becomes `viewed`.
- Position state remains `flat`.
- Delivery remains allowed while the intent is still executable.

### TC-ENTITY-ACT-API-008 Instrument action resolves to pair context
Automation: tests/test_api_v2.py::test_v2_instrument_actions_resolve_pair_context_and_store_execution
Preconditions:
- Instrument appears in `/api/v2/signals/actionability?entity_type=instrument`.
Steps:
1. POST `/api/v2/entities/instrument/{entity_id}/signals/actions` with `action=mark_viewed` and matching `intent_id`.
Expected:
- Response status `ok`.
- Response keeps `entity_ref.entity_type=instrument` and includes resolved `pair_ref`/`pair_id`.
- Execution is stored against resolved pair ledger as canonical `mark_viewed`.

### TC-ENTITY-ACT-API-009 Ambiguous instrument requires explicit pair hint
Automation: tests/test_api_v2.py::test_v2_instrument_actions_require_pair_hint_when_ambiguous
Preconditions:
- One instrument participates in multiple actionable pairs.
Steps:
1. POST `/api/v2/entities/instrument/{entity_id}/signals/actions` without `pair_id`.
Expected:
- Response `409` with `error=ambiguous_instrument_entity`.
- Payload includes candidate pair ids for explicit disambiguation.
