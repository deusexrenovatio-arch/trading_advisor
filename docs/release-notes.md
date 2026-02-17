# Release Notes

## 2026-02-17 - Minute portfolio HPO parity + execution quality projection

Summary
- Unified portfolio HPO evaluation with minute replay execution semantics.
- Added explicit execution model controls to backtest contracts.
- Exposed execution quality block in `/api/signals`, matching top-pairs projection semantics.

Changed
- Backtest execution contract:
  - `execution.execution_model` (`MINUTE_REPLAY` | `DAILY_V2`)
  - `execution.minute_fail_fast`
- Rebalance contract:
  - `rebalance.target_utilization`
- Rebalance config mapping:
  - `rebalance.cadence=daily` now resolves to `soft_rebalance_frequency=DAILY`.
- HPO runner:
  - `scope=PORTFOLIO` now evaluates folds through minute portfolio path
    (`compute_minute_portfolio_window_metrics`) instead of pair-mean slicing.
  - Trial payload now includes:
    - `evaluation_scope`
    - `objective_breakdown`
- Minute period metrics:
  - deterministic-safe aggregate defaults for missing values (no NaN-only comparisons in parity checks).
- UI/API:
  - `/api/signals` now returns `execution_quality` block, aligned with `/api/top-pairs`.

Verification
- `pytest -q tests/test_ui_api.py tests/backtest_v2/test_minute_portfolio_engine.py tests/hpo/test_minute_period_pnl.py tests/hpo/test_portfolio_objective.py`
- `pytest -q tests/perf/test_minute_runtime.py tests/perf/test_minute_portfolio_runtime.py tests/perf/test_hpo_portfolio_runtime.py`
- `pytest -q tests/test_config_resolver.py tests/hpo/test_runner.py tests/hpo/test_runtime_quality.py tests/test_backtest_forward_api.py`
- `pytest -q tests/test_ui_unified_runtime.py tests/test_ui_api.py`

## 2026-02-17 - Skill governance gates in docs and acceptance coverage

Summary
- Added explicit process gates for skill lifecycle: start, recheck, and pre-push.
- Linked development workflow policy to manual acceptance scenarios and test cases.
- Clarified architecture map update rule for process-only documentation changes.
- Added automated local and CI enforcement for governance gates.

Changed
- Updated skill governance and dependencies:
  - `AGENTS.md`
  - `.cursor/skills/*/SKILL.md`
- Added process acceptance scenarios:
  - `configs/acceptance_scenarios.yaml`
    - `dev-skill-start-gate`
    - `dev-skill-recheck-gate`
    - `dev-skill-prepush-gate`
- Extended acceptance runner with manual scenario type:
  - `scripts/acceptance_check.py` (`type: manual` -> skip with explicit marker)
- Added repository skill validator:
  - `scripts/validate_skills.py`
- Added git hook automation:
  - `.githooks/pre-push`
  - `scripts/install_git_hooks.py`
- Added local branch safety in pre-push:
  - direct push to `main` is blocked by default,
  - explicit override via `MOEX_CARRY_ALLOW_MAIN_PUSH=1`.
- Added pre-push frontend install fallback switch:
  - `MOEX_CARRY_SKIP_NPM_CI=1` skips only `npm ci` while keeping `lint/build` checks.
- CI now has fail-fast governance gate before backend/frontend jobs:
  - `.github/workflows/ci.yml` (`governance` job)
- Added process workflow test cases:
  - `docs/test-cases.md`
    - `TC-DEV-WF-001`
    - `TC-DEV-WF-002`
    - `TC-DEV-WF-003`
- Linked workflow policy with acceptance coverage:
  - `docs/DEV_WORKFLOW.md`
- Added install note for local pre-push hooks:
  - `README.md`
- Updated architecture map maintenance instructions:
  - `docs/architecture/architecture-map-v2.md`

Verification
- `python scripts/validate_test_cases.py`
- `python scripts/validate_skills.py`
- `python scripts/sync_architecture_map.py --check`
- `python -m py_compile scripts/acceptance_check.py scripts/validate_test_cases.py scripts/validate_skills.py scripts/install_git_hooks.py`
- skill validation (`quick_validate.py`) for all `.cursor/skills/*`

## 2026-02-16 - Two-stage HPO quality review + canonical minute defaults

Summary
- Added two-stage HPO: fast objective search first, then minute execution quality review on top-N candidates.
- Fixed canonical minute strategy defaults in `BacktestRequest` to match production baseline.
- Kept optimization speed by computing heavy fill-quality only for shortlisted candidates.

Changed
- HPO optimization contract now includes quality-review controls:
  - `quality_review_enabled`
  - `quality_top_n`
  - `quality_min_trades_closed_total`
  - `quality_max_unfilled_entry_rate`
  - `quality_max_forced_exit_rate`
  - `quality_max_entry_wait_min_closed`
  - `quality_max_exit_wait_min_closed`
  - `quality_lambda_unfilled`
  - `quality_lambda_forced`
  - `quality_lambda_wait`
- HPO runtime now writes `result.quality_review` with:
  - gate pass/fail by candidate,
  - quality penalty,
  - quality-adjusted objective,
  - minute execution metrics for reviewed candidates.
- v2 HPO status gate now considers quality result:
  - `promotion_gate=fail` when quality gate fails for all reviewed candidates.
- Canonical minute defaults in `BacktestStrategyConfig`:
  - `signal_exec_lag_days=0`
  - `execution_lag_minutes=30`
  - `execution_max_wait_minutes=360`
  - `entry_price_tolerance_pct=0.02`
  - `entry_stock_tolerance_pct=0.02`
  - `entry_future_tolerance_pct=0.025`
  - `entry_spread_tolerance_pct=0.03`

Verification
- `pytest -q tests/hpo/test_runtime_quality.py tests/hpo/test_runner.py tests/hpo/test_objective.py`
- `pytest -q tests/test_api_v2.py tests/test_backtest_forward_api.py tests/test_backtest_defaults.py`

## 2026-02-17 - Pending-entry lifecycle + Telegram delivery unification

Summary
- Unified active-signal delivery rules between backend API and Telegram worker.
- Added pending-entry intent promotion for both open and flat position states.
- Switched `signals --history-days` unified mode to incremental data enrichment instead of full legacy fetch on every run.

Changed
- Active signal lifecycle:
  - `GET /api/signals/active` can promote latest unused `enter` intent over `hold` rows within configurable TTL.
  - Promotion works for `hold_open` (position is open) and `hold_flat` (no open legs) states.
  - Promotion stops only after explicit operator usage (`ack`/action), not just because position is open.
- Delivery contract:
  - `GET /api/v2/signals/active` now includes:
    - `delivery_action`
    - `delivery_allowed`
    - `delivery_suppressed_reason`
    - `entry_signal_expired`
    - `entry_range_eligible`
  - Delivery computation moved to shared module `src/moex_carry/signals_delivery.py`.
- Telegram worker:
  - Prefers `/api/v2/signals/active` with fallback to `/api/signals/active`.
  - Uses same shared delivery rules as backend API.
  - Added per-pair cooldown for new `enter` fingerprints (`telegram.enter_resend_cooldown_minutes`).
  - Sends one out-of-range update when already-sent `enter` leaves original entry corridor.
- Unified runtime entry plan:
  - Unified snapshot rows include entry bounds for both legs and spread (`entry_*` fields) computed from latest market snapshot.
- Backfill/runtime:
  - `moex_carry.cli signals --history-days N` in unified mode now uses incremental minute ingest + unified snapshot replay.
  - Reference data (`shares/futures/key_rates`) is refreshed only when missing/stale, not on every backfill loop.

Config additions
- `ui.signal_entry_intent_ttl_hours` (default `72`)
- `telegram.enter_resend_cooldown_minutes` (default `60`)

Verification
- `pytest -q tests/test_signal_api.py tests/test_telegram_worker.py tests/test_signal_cycle.py`
- `python -m moex_carry.cli signals --config configs/default.yaml --history-days 7 --max-pairs 0`

## 2026-02-16 - Minute default refresh + true incremental replay

Summary
- Switched backend signal refresh default cadence to 60 seconds.
- Implemented true incremental replay with per-pair disk checkpoints and overlap-safe replay.
- Made UI/API default reads serve latest backend-produced last-good outputs.

Changed
- Config defaults:
  - `ui.signal_refresh_interval_sec=60`
  - `ui.signal_refresh_daily_time=null`
  - `ui.incremental_replay_enabled=true`
  - `ui.incremental_overlap_minutes=180`
  - `ui.incremental_checkpoint_dir=./data/state/incremental_replay`
  - `ui.incremental_checkpoint_interval_minutes=60`
- New modules:
  - `src/moex_carry/minute_ingest/` for incremental minute upsert + watermark/cursor state.
  - `src/moex_carry/signal_replay/incremental.py` for true incremental replay engine.
- Replay state-machine now supports resumable execution state in `pipeline._apply_spread_carry_signals(...)`.
- Scheduler semantics:
  - scheduled refresh path uses non-force incremental route,
  - manual `POST /api/signals/refresh` keeps forced full fallback path.
- `GET /api/signals/refresh-status` enriched with incremental telemetry:
  - `incremental_enabled`, data watermarks, pairs recompute/reuse/skip counters, skip reason.
- UI/API default data serving:
  - `/api/top-pairs`, `/api/signals`, `/api/backtests` return latest backend outputs by default,
  - optional `fresh=1` enables on-demand in-process read path.

Verification
- `pytest -q tests/test_signal_replay_incremental.py tests/test_signal_replay_core.py tests/test_signal_replay_golden_parity.py tests/test_execution_replay.py tests/test_ui_unified_runtime.py tests/test_ui_api.py`
- `pytest -q tests/test_config_loading.py tests/test_signal_api.py tests/test_signal_cycle.py tests/test_ui_data_parsing.py`

## 2026-02-13 - Interactive architecture dependency map (D3)

Summary
- Added a single interactive map for components, entities, APIs, storages, and dependency flows.
- Map is aligned with v2 layers/contracts and workspace IA.

Changed
- Added D3 architecture visualization:
  - `docs/architecture/architecture-map-d3.html`
  - `docs/architecture/architecture-map-data.js`
  - `docs/architecture/architecture-map-v2.md`
- Updated architecture documentation index:
  - `docs/architecture/trading-advisor.md` now links the new map.
- Coverage includes:
  - layer boundaries (L1..L6),
  - backend module dependencies,
  - `/api/v2/*` surface + v1 adapter bridge,
  - canonical entity lineage,
  - UI workspace-to-API flows,
  - persistence surfaces (SQLite/JSONL/runtime files).

Verification
- Data file parse check:
  - `node -e \"global.window={}; require('./docs/architecture/architecture-map-data.js'); console.log(window.ARCH_MAP_DATA.nodes.length, window.ARCH_MAP_DATA.links.length)\"`

## 2026-02-13 - Sprint 4 follow-up: runbook hardening + v2 surface cleanup

Summary
- Finalized Sprint 4 operational documentation to incident-grade runbooks.
- Removed remaining frontend dependencies on v1 signal/decision action read paths.
- Added explicit governance decision for atomic commit slicing and structured patch notes.

Changed
- Runbooks hardened with concrete triage flows, metric paths, and escalation criteria:
  - `docs/runbooks/iss-degradation.md`
  - `docs/runbooks/execution-failures.md`
  - `docs/runbooks/ops-slo-alerts.md`
  - `docs/runbooks/signal-action-audit.md`
- v2 endpoint usage aligned in UI/API layer:
  - `GET /api/v2/top-pairs`
  - `GET /api/v2/signals/history`
  - `GET /api/v2/signals/executions`
  - `POST /api/v2/signals/{signal_id}/actions`
- Acceptance smoke migrated to v2-first routes:
  - `configs/acceptance_scenarios.yaml` now uses `/api/v2/decisions/view`, `/api/v2/top-pairs`,
    `/api/v2/signals/active`, `/api/v2/signals/history`.
  - Added dynamic scenario `signals-action-v2` (`active -> /api/v2/signals/{signal_id}/actions`).
  - `signals-execute` acceptance switched from v1 `/api/signals/execute` to
    v2 `active -> /api/v2/signals/{signal_id}/actions` with `ok|duplicate|blocked` outcomes.
  - `scripts/acceptance_check.py` now supports `signal_action` and parameterized source/url templates
    for `spread_series`, `backtest_run`, and `history_date_range`.
  - Runner now normalizes YAML `date/datetime` payload values to ISO strings before POST.
  - Runtime-prerequisite scenarios use explicit skip rules:
    `backtest-run` skips on empty pair source,
    `forward-start`/`hpo` skip on `400 Missing raw data`,
    `forward-status`/`hpo-status` skip on `400 no_active_run`.
- Acceptance documentation updated:
  - `docs/test-cases.md` aligned with v2 URLs and new case `TC-SIG-ACT-API-003`.
- v2 action response for decisions now includes explicit refs used by UI:
  - `decision_ref`
  - `execution_ref`
- Product governance updated:
  - `docs/planning/product-decisions.md` now records commit/patch-note policy.

Verification
- Backend:
  - `python scripts/validate_test_cases.py`
  - `python scripts/acceptance_check.py --skip-frontend --allow-empty`
  - `python -m pytest tests/test_api_v2.py`
  - `python -m pytest tests/test_ui_api.py`
  - `python -m pytest tests/test_signal_api.py`
- Frontend:
  - `npm --prefix ui-web run lint`
  - `npm --prefix ui-web run build`

Risk / Rollback
- Risk: low-to-medium (API path migration in frontend and operator runbook behavior).
- Rollback strategy:
  - keep v1 adapters enabled for two releases,
  - revert frontend calls to v1 adapters only if critical regression is detected,
  - no schema rollback required for documentation-only updates.

## 2026-02-13 - Contract-first Sprint 1 baseline (v2 endpoints + v1 adapters)

Changed
- Added Sprint 1 contract endpoints:
  - `GET /api/v2/decision-view` (alias of `GET /api/v2/decisions/view`),
  - `POST /api/v2/decisions/{decision_id}/actions`,
  - `POST /api/v2/pretrade/check`.
- Added UI domain-boundary gate:
  - `npm --prefix ui-web run lint:ui-domain-boundary`,
  - wired into `npm --prefix ui-web run lint` to fail if business signal statuses are computed in frontend.
- Added explicit v1 deprecation headers on legacy routes:
  - `Deprecation: true`
  - `Sunset: Wed, 01 Jul 2026 00:00:00 GMT`
  - `Warning: 299 ... migrate to /api/v2/...`
  - `Link: <...>; rel="successor-version"`
- Added route-based workspace navigation in UI:
  - `/trade-console/*`
  - `/decision-audit`
  - `/research-system/*`
  - `/news-intelligence`
  - `/portfolio-control`
- Completed Signals UI decomposition in `MarketTablesTab`:
  - `SignalQueuePanel`
  - `DecisionHistoryPanel`
  - `DecisionPanel`
  - `ExecutionPanel`
  - `PretradePanel` (pre-trade diagnostics block extracted from container)
- Moved Signals status/action adapters out of hook:
  - new `ui-web/src/features/market/signalViewModel.ts`
  - `useMarketTables.ts` now keeps orchestration/state and uses external view-model helpers.
- Updated boundary lint gate for new helper location:
  - `ui-web/scripts/ui-domain-boundary-gate.mjs` now validates backend-sourced `signal_action_effective` in `signalViewModel.ts`.
- Added workspace KPI strip in `App`:
  - `tab_switch_count`
  - `time_to_first_action_sec`
  - `blocked_action_rate` (entry-intent signals blocked by pre-trade in Signals view)
- `useMarketTables` now accepts `onOperatorAction` callback to register first manual action events.
- Extracted workspace data orchestration hooks:
  - `ui-web/src/features/news/useNewsIntelligence.ts`
  - `ui-web/src/features/portfolio/usePortfolioControl.ts`
  - `NewsIntelligenceTab` and `PortfolioControlTab` remain presentation-focused.
- Added workspace e2e smoke coverage:
  - `ui-web/tests/workspace-news-portfolio.spec.ts` (route + filters + rebalance commit flow).
- Added acceptance coverage for workspace modules:
  - `news-feed-v2` (`TC-NEWS-API-001`, `TC-NEWS-UI-001`)
  - `portfolio-rebalance-v2` (`TC-PORT-API-001`, `TC-PORT-UI-001`)
- Added domain services:
  - `src/moex_carry/domain/decision_engine.py` for lifecycle/gate/action normalization,
  - `src/moex_carry/domain/pretrade_service.py` for pretrade status and runtime param projection.
- Updated v1 adapter behavior:
  - `POST /api/decisions/{decision_id}/action` now routes through v2 action logic.
  - `POST /api/signals/execute` now uses unified signal-action writer with idempotency support (`idempotency_key`) while keeping legacy response shape (`status`, `order_id`).
- Strengthened v2 decision projection audit surface:
  - `GET /api/v2/decisions/view` now includes backend-owned `decision_ref` and `execution_ref`
    with latest action/request linkage (`action_id`, `request_id`, `idempotency_key`, timestamps).
- Added rollout-safe projection source switch:
  - new config flag `ui.ff_db_projection_source` (`FF_DB_PROJECTION_SOURCE`) to prefer DB projection.
  - if DB projection has no rows yet, endpoint falls back to JSONL and marks rows with
    `projection_source=jsonl_fallback`.
- Added projection migration tooling:
  - `scripts/backfill_decision_projection.py` (`backfill|parity|all` modes),
  - parity gate with threshold support (`--parity-threshold`, default `0.995`),
  - source-of-truth workflow documented in `docs/data/source-of-truth.md`.
- Added decision projection write-through:
  - `DecisionLogStore.append` now upserts `decision_view_projection` on every new decision view append.
  - historical backfill script remains for bootstrap of existing JSONL history.
- Added execution safety policy controls:
  - new config flags `ui.ff_fail_closed_execution` and `ui.auto_unwind_timeout_sec`,
  - `POST /api/v2/signals/{signal_id}/actions` can return `status=blocked` on fail-closed rules for entry,
  - privileged override path (`fail_closed_override`) requires explicit reason and is audited in `signal_executions.note`.
- Added auto-unwind policy endpoint:
  - `POST /api/v2/policies/auto-unwind/run` for stale one-leg imbalance mitigation,
  - supports `dry_run`, deterministic idempotency, and summary counters (`triggered|duplicate|blocked|error`).
- Added operational runbooks:
  - `docs/runbooks/iss-degradation.md`,
  - `docs/runbooks/execution-failures.md`,
  - `docs/runbooks/ops-slo-alerts.md`.
- Added runtime observability endpoints:
  - `GET /api/v2/ops/health` (DB readiness + signal refresh state),
  - `GET /api/v2/ops/slo` (endpoint latency/error stats, 15m event counters, alert flags).
- Added in-memory SLO instrumentation for critical flows:
  - `v2_signals_actions` (execution rejection spikes),
  - `v2_pretrade_check` (pretrade failures/degraded checks),
  - `v2_auto_unwind_run` (policy trigger and error counters).

Verification
- Frontend:
  - `npm --prefix ui-web run lint`
  - `npm --prefix ui-web run build`
  - `npm --prefix ui-web run test:e2e -- workspace-news-portfolio.spec.ts`
- UI/API regression:
  - `python -m pytest -q tests/test_ui_api.py tests/test_spread_series.py`
  - `python -m pytest -q tests/test_api_v2.py tests/test_signal_api.py`
  - `python -m pytest -q tests/test_api_v2.py -k "ops_health_and_slo_observability"`
  - `python scripts/validate_test_cases.py`

Deprecation plan
- v1 endpoints remain supported via adapter for 2 releases:
  - `POST /api/decisions/{decision_id}/action`
  - `GET /api/decision-view`
  - `GET /api/pretrade/check`
- Removal target: after 2 stable releases once all UI and bots switch to v2.

## 2026-02-10 - MOEX ISS IP Fallback (VPN-friendly transport resilience)

Changed
- Added connector-level ISS fallback by IP in `MoexIssClient` for transport failures:
  - primary path: configured `moex.base_url` (usually `https://iss.moex.com`),
  - fallback path: `moex.fallback_ips` with HTTPS `Host/SNI` pinned to original host,
  - triggers only on transport errors (`SSLError`, `ConnectionError`, `Timeout`).
- Fast-fallback behavior improved to reduce UI latency under broken primary route:
  - with configured `fallback_ips`, primary transport path is tried once per request (no long retry chain before fallback),
  - failover state is cached per host for a cooldown window, so subsequent requests skip slow primary probes and go directly to fallback.
- Fallback is wired into all main backend flows:
  - data fetch/history,
  - pair/signal/backtest pipelines,
  - pre-trade API checks.
- New config key:
  - `moex.fallback_ips` (default now includes `85.118.181.8`).

Tests
- Added ISS client tests for:
  - fallback after primary TLS transport failure,
  - host-level failover reuse across client instances,
  - no fallback on non-retryable HTTP errors (`404`).

## 2026-02-10 - Pre-trade Transport Fail-Open for ISS Manual Mode

Changed
- `GET /api/pretrade/check` no longer returns `500` on ISS transport failures (`SSLError`, `ConnectionError`, `Timeout`) when `ui.pretrade_fail_open_on_transport_error=true`.
- Endpoint now returns a degraded manual-drive payload:
  - `status=PLACE`, `ready_to_place=true`, `manual_confirm_required=true`,
  - `degraded=true`,
  - `advisory_reasons` includes `iss_transport_error`,
  - `diagnostics.transport_error` contains connector error text.
- Payload shape remains actionable (`pair`, `targets`, `order_price_bands`, `volume_requirements`, `params`) so Signals UI keeps working without transport-error hard blocking.

Tests
- Added `tests/test_ui_api.py::test_pretrade_check_endpoint_fail_opens_on_iss_transport_error`.

## 2026-02-10 - MOEX ISS Transport Retry Hardening

Changed
- Hardened MOEX ISS connector against transient transport failures (including SSL EOF errors):
  - retries on `SSLError`, `ConnectionError`, `Timeout`,
  - retries on retryable HTTP statuses (`408`, `425`, `429`, `500`, `502`, `503`, `504`),
  - exponential backoff with configurable caps.
- Added MOEX connector config keys:
  - `moex.request_max_retries`
  - `moex.request_retry_backoff_sec`
  - `moex.request_retry_max_backoff_sec`
- Updated client initialization paths to pass retry settings from config:
  - data fetch/history/pipeline/pre-trade endpoints.

Tests
- Added retry tests for ISS client:
  - SSL EOF then success,
  - HTTP 503 retry then success,
  - no retry on HTTP 404.

## 2026-02-10 - Pre-trade ISS Manual-Drive Policy (futures gates advisory)

Changed
- `GET /api/pretrade/check` now uses ISS manual-drive blocking policy for entry readiness:
  - `ready_to_place` is blocked only by stock-leg gates (`stock_quote_pass`, `stock_price_pass`, `stock_volume_pass`).
  - futures/spread/sync gates remain computed and returned as diagnostics, but do not block execution.
- Pre-trade payload now includes:
  - `gate_policy` with `blocking_gates` and `advisory_gates`,
  - `quote_pass_strict` (strict two-leg quote diagnostic),
  - `advisory_reasons` for non-blocking futures/sync/spread issues.

Tests
- Updated: `tests/test_pretrade_delay_gate.py`
- Verified: `tests/test_ui_api.py`

Operational notes
- This mode is for ISS delayed/manual-drive operations.
- When live feed is available, switch to strict two-leg blocking policy.

## 2026-02-09 - Pre-trade Delay Gate + Orderbook Entry Gate (ISS REST)

Release type
- Minor (backward-compatible additions in API/UI and strategy gates).

Added
- New API endpoint `GET /api/pretrade/check` for delayed pre-trade readiness on two-leg stock/futures entries.
- New backend module `src/moex_carry/pretrade/delay_gate.py` with deterministic checks:
  - leg price bands (both legs),
  - delayed spread band consistency,
  - snapshot sync gate,
  - session volume sufficiency gate.
- Endpoint response payload now includes:
  - `status`, `ready_to_place`, `manual_confirm_required`,
  - `order_price_bands`, `volume_requirements`,
  - `gates`, `hits`, `reasons`, `last_snapshot`, `params`.
- Signals UI details panel now includes a dedicated pre-trade block with:
  - live refresh action (`Обновить pre-trade`),
  - status/reasons,
  - order price bands,
  - volume requirements,
  - gate statuses and hit counters.
- Signals UI detail tab now groups execution metrics into readable sections:
  - `Контекст сигнала`,
  - `План входа` (entry corridors),
  - `Риск и стоп-уровни` (TP/SL),
  - `Прогноз выхода` (horizon/date/probabilities),
  - `Метрики модели` (curated quality subset, no raw dump).
- Signals detail tabs are now data-driven:
  - `Сигнал` is the default tab for Signals rows,
  - `Обзор` / `Альфа` / `Ликвидность` are shown only when data is present for the selected row,
  - UI shows coverage counters for plan fields and an explicit note when `entry_*` / `tp/sl` / `forecast_*` are absent in API payload.
- Field metadata/localization improvements:
  - entry/TP/SL/forecast labels/tooltips translated and clarified,
  - orderbook quality fields now have labels/tooltips,
  - pre-trade fields (`status`, price bands, gates, hits, reasons) now have readable labels + value mapping.
- Signal payload now includes a trading plan with actionable execution data:
  - entry corridors for stock/futures/spread (`entry_*`),
  - TP/SL levels by spread (`tp_spread_*`, `sl_spread_*`),
  - projected exit horizon/date (`forecast_exit_days`, `forecast_exit_date`),
  - TP/SL hit probabilities (`forecast_tp_probability`, `forecast_sl_probability`).
- Signals table now highlights action-oriented columns:
  - entry price corridors for stock and futures,
  - TP/SL spread levels,
  - forecast exit days.
- Acceptance updates:
  - `configs/acceptance_scenarios.yaml`: new `pretrade-check` scenario,
  - `docs/test-cases.md`: `TC-PRETRADE-API-001`, `TC-PRETRADE-UI-001`,
  - `scripts/acceptance_check.py`: support for `api_object` validation type.

Changed
- Intraday market data parsing now extracts orderbook depth and quote age for both legs:
  - `bid_depth`, `ask_depth`, `quote_age_sec`.
- Signal APIs now expose `signal_metrics` fields at top level (while keeping nested `signal_metrics`):
  - `GET /api/signals`
  - `GET /api/signals/active`
  - `GET /api/signals/history`
- Signal API contract for `signals/*` is now stabilized for legacy/incomplete rows:
  - execution-plan/model keys are always present in payload (`entry_*`, `tp/sl_*`, `forecast_*`, orderbook/model scores),
  - missing values are returned as `null` instead of absent keys.
- `GET /api/pretrade/check` enforces strict quote gating for two-leg execution:
  - bid/ask absence on required execution sides blocks `ready_to_place`,
  - response exposes dedicated quote gates/hits (`quote_pass`, `stock_quote_pass`, `fut_quote_pass`).
- Signal diagnostics now include ISS quote/depth availability fields:
  - `orderbook_stock_quote_available`, `orderbook_fut_quote_available`,
  - `orderbook_stock_depth_available`, `orderbook_fut_depth_available`,
  - `orderbook_data_warnings` (e.g. `orderbook_fut_quote_missing`, `orderbook_fut_depth_missing`).
- Added config key `spread_carry_alpha.entry_price_tolerance_pct`:
  - used for entry corridor generation in signals,
  - used as default `eps` in `GET /api/pretrade/check` when `eps` is not passed.
- Strategy config (`SpreadCarryAlphaConfig`) now supports orderbook entry controls:
  - `require_live_orderbook_for_entry`,
  - min depth thresholds (stock/futures),
  - max quote age thresholds (stock/futures),
  - max bid/ask imbalance thresholds (stock/futures).
- Pair pipeline now evaluates an orderbook gate during entry decisioning:
  - new decision path `SKIP_ORDERBOOK`,
  - reasons and metrics persisted in pair output (`orderbook_pass`, depths, ages, imbalance, `orderbook_reasons`).
- Signals UI pre-trade block is now de-noised:
  - default view shows only decision-critical items (status, reasons, critical gates, order corridor, volume requirements),
  - detailed counters/snapshots/params moved into collapsible `Расширенная диагностика`.
- Signals detail tab now renders `Итоговый сигнал` before `План входа`:
  - includes compact pre-trade status chips for two-leg entry readiness,
  - computes effective action with pre-trade constraints (`enter`, `hold_pretrade`, `check_pretrade`).
- Signals list (`Сигналы`) now shows effective action in the main `Сигнал` column before opening details:
  - value reflects pre-trade state (`Вход разрешен`, `Вход заблокирован pre-trade`, `Ожидает pre-trade проверки`),
  - pre-trade checks are prefetched in background for top rows.
  - top toolbar filter `Сигнал` is aligned with these effective statuses.
- Signal execution UX now enforces pre-trade readiness:
  - entry-side `Исполнить` is disabled until pre-trade confirms `ready_to_place=true`.
- Signals UI model block is split into:
  - `Проверки исполнимости` (quote/depth availability and gate pass),
  - collapsible `Технические метрики модели` for secondary diagnostics.
- Localization coverage expanded for new delayed/orderbook fields:
  - `quote_pass`, `stock_quote_pass`, `fut_quote_pass`,
  - `stock_quote_hits`, `fut_quote_hits`,
  - `orderbook_*_quote_available`, `orderbook_*_depth_available`, `orderbook_data_warnings`,
  - pre-trade reasons `stock_quote_missing`, `fut_quote_missing`.

Fixed
- UI typing/lint/build cleanup in tabs and shared helpers:
  - `renderFieldLabel` now consistently supports `ReactNode` where tooltips are rendered,
  - param section tuple typing fixed,
  - minor hook dependency and test lint fixes.

Verification
- Backend/API tests:
  - `tests/test_ui_api.py`
  - `tests/test_pretrade_delay_gate.py`
  - `tests/test_marketdata_points.py`
  - `tests/test_intraday_marketdata_scaling.py`
  - `tests/test_signal_api.py`
  - `tests/test_signal_trade_plan.py`
- Frontend checks:
  - `npm --prefix ui-web run lint`
  - `npm --prefix ui-web run build`
  - `ui-web/tests/top-signals.spec.ts`
  - `ui-web/tests/decisions.spec.ts`

Operational notes
- Designed for ISS REST without auth and delayed quotes; `manual_confirm_required` remains mandatory.
- For ISS-only operations, use pre-trade gate as delayed readiness evidence, not as a replacement for terminal-side real-time verification.

Rollback
- Disable strict orderbook entry blocking by keeping `spread_carry_alpha.require_live_orderbook_for_entry: false`.
- UI/API additions are additive; rollback can be performed by reverting this release commit.

## 2026-01-28 - HPO Objective Modes + Gates + Annualization

Added
- HPO supports `optimization.metric` + `optimization.mode` (max/min) with updated objective handling.
- Entry gates now respect `strategy.z_entry_threshold`, `min_floor_score`, `min_alpha_score`.
- Backtest v2/HPO annualization honors `rates.use_trading_days` (252 vs 365).
- HPO UI supports full JSON request override with form defaults as fallback.

Notes
- Dividend PV remains per-stock (no change required).

## 2026-01-28 - HPO Async API + Status

Added
- `/api/hpo/run` wired to real HPO runs (async).
- `/api/hpo/status` to fetch live run status + results when completed.
- UI HPO tab shows run id and progress while polling status.

Notes
- Backtest v2 optimizations (precompute + fast alpha) are preserved.

## 2026-01-28 - UI Architecture Refactor (Feature Tabs + Shared Helpers)

Added
- Feature-level tabs for Top pairs / Signals / Backtests with a shared MarketTables base.
- Shared view helpers for Backtest/HPO and parameter inputs to keep App orchestration-only.
- Decision server filters (strategy/instrument/risk/news/date) preserved and documented.

Notes
- No changes to backend strategy logic or API contracts.

## 2026-01-27 - Backtest v2 Params UX

Added
- Human-friendly labels/tooltips for Backtest v2 parameters (no raw technical keys).
- Dict parameters (e.g., allocation weights) render as labeled rows with numeric inputs.
- Param filter matches labels and sections are ordered (Test/Universe/Execution/...).
- Value label mappings for key enum-like params (price_mode, capital_base_mode, cadence).

## 2026-01-27 - UI: Russian localization + metrics UX

Added
- Russian UI labels across Decisions, Top Pairs, Signals, Backtests, Forward, and HPO tabs.
- Unified field labels/formatting (percent/bps/currency/days) via field metadata.
- Metric tooltips with formula + interpretation in table headers and detail panels.
- Default Signals history range (last 7 days).
- Basket weights formatted as percentages with consistent labels.

Notes
- Detail grids filter out row-duplicated fields where possible to reduce repetition.

## 2026-01-27 - C/D/E Completion: API/CLI + HPO + UI

Added
- Completed API/CLI + UI surface for Backtest v2, Forward status, and HPO (HPO API validates payloads and returns stub status).

Notes
- Backtest v2 performance optimizations (precompute cache + fast alpha path) remain intact.

## 2026-01-27 - UI Backtest v2, Forward Status, HPO

Added
- Backtest v2 tab with parameter specs form, run action, and summary/equity/trades views.
- Forward status tab with last equity/trade/alert panels and state snapshot.
- HPO tab with search space form and leaderboard view.
- Playwright UI smoke coverage + acceptance scenarios for new tabs.

Notes
- UI uses API calls only; backend logic and Backtest v2 optimizations remain unchanged.

## 2026-01-27 - HPO Module (Backtest v2 Black Box)

Added
- `src/moex_carry/hpo/` package for HPO on top of Backtest v2 (search space parsing, walk-forward folds with embargo, objective/constraints, aggregation).
- RANDOM sampler and simplified TPE sampler.
- Fold evaluation modes: CONTINUOUS (single run per fold, windowed metrics) and WARMUP_THEN_FLAT (warmup to reset equity).
- Unit tests for fold generation, constraints -> -INF, leaderboard ordering/best config.

Notes
- Backtest v2 remains unchanged; HPO uses it as a black box via runtime cached runner.
- API/CLI for HPO remain unchanged (endpoint still stub).

## 2026-01-27 - Backtest v2 + Forward API/CLI Wiring

Added
- API endpoints: `POST /api/backtest/run`, `POST /api/forward/start`, `GET /api/forward/status`, `POST /api/hpo/run` (stub).
- CLI commands: `backtest_v2`, `forward_start`, `forward_status`.
- History-backed runtime adapters for Backtest v2 and Forward (uses `data/history/` candles + `raw/key_rates.csv`).
- Precompute cache for Backtest v2 runs to preserve fast alpha/precompute paths.
- Integration tests for backtest/forward API wiring and validation errors.

Notes
- No changes to Backtest v2/Forward internal logic or decision_log.
- HPO endpoint validates payload only (stub).


## 2026-01-27 - Forward Paper Engine

Added
- ForwardTestEngine with EOD -> OPEN -> after-close paper cycle using SnapshotBuilder + PortfolioRebalanceController.
- PaperBroker for simulated fills and JsonStateStore for state/trade/equity/alert persistence.
- Forward alert codes: DATA_STALE, MISSING_QUOTES, SPREAD_TOO_WIDE, DRAWDOWN_KILL, TURNOVER_SPIKE.
- Unit tests for forward engine persistence, daily cycle, and alerting.
- Documentation updates for US-09 and backend module catalog; frontend behavior checklist updated for spread-series fields.

Notes
- Backtest v2 and legacy backtest remain unchanged.


## 2026-01-27 - Backtest v2 Performance & Batch Scoring

Added
- Backtest v2 precompute flow with cached snapshots/bars.
- Feature matrices and batch scoring helpers for fast parameter sweeps.
- Fast alpha matrices with optional numba acceleration (numpy fallback).
- Fast alpha cache integrated into backtest v2 when precompute data is used.
- `strategy.spread_history_days` default (90) and validation.
- Unit tests for v2 engine, batch scoring, and fast alpha.

Notes
- Fast alpha is used only when `precomputed` data is provided; otherwise the classic alpha path runs.
- Numba is optional; install it to unlock JIT acceleration.

## 2026-01-26 - Stage 4: Trade Returns & UI Metrics

Added
- Trade PnL cash, net return (pre-tax), annualized return, and hold days in spread series.
- Average annualized return over last 5 exits for Top Pairs.
- UI table column and Alpha detail field for average annual return.
- UI trade summary line now shows pnl/net/annual/hold per cycle.
- Acceptance + UI tests updated to enforce new field.

Notes
- Net returns are pre-tax (dividend/profit taxes not applied in series).
- Reload recomputes signals on fresh market data and may differ from cached/top_pairs.


## 2026-01-26 - Stage 1: Contracts and Config

Added
- Portfolio domain dataclasses: PairSpec, DailyInstrumentBar, SnapshotPerPair, PositionState, PortfolioState, Order, Fill.
- Backtest/forward/HPO request contracts and ParameterSpec contract.
- Config resolver with AUTO resolution, cost stress multiplier, and validations.
- Parameter spec registry and `/api/params/specs` endpoint.
- Tests for resolver, parameter specs, and API endpoint.

Notes
- No changes to backtest/forward/HPO business logic.
- No changes to decision_log or decision_view schemas.

## 2026-01-26 - Stage 2: Calculations and SnapshotBuilder

Added
- Execution model support for BID/ASK and OHLC synthetic pricing with bps/tick slippage.
- Cost model helpers for fee per share/contract and round-trip cost/RTC percent.
- Dividend PV and funding cost helpers with day-count support.
- Spread/floor/liquidity calculations wired for SnapshotBuilder.
- SnapshotBuilder to assemble SnapshotPerPair universe with exec spreads, rtc_pct, floor metrics, and liquidity flags.
- Unit tests covering execution OHLC, dividends PV, margin-aware floor, and snapshot builder.

Notes
- Strategy, rebalance, and backtest business logic unchanged.

## 2026-01-26 - Stage 3: PortfolioRebalanceController

Added
- Portfolio rebalance controller implementing hard exits, TP/SL, rotation, band-rebalance, and turnover caps.
- Allocation methods: EQUAL, SCORE_WEIGHTED, SCORE_RISK_PARITY, FLOOR_PLUS_ALPHA_OVERLAY.
- Rebalance contracts (RebalanceConfig, RebalanceResult, TargetPosition) and portfolio utilities.
- Portfolio tests covering exits, hysteresis, rotation, band-rebalance, turnover cap, and risk-parity weights.

Notes
- Backtest engine and decision_log/decision_view schemas unchanged.

