# Release Notes

## 2026-02-12 - Unified Minute-First Runtime for Market UI Endpoints

Changed
- Market UI endpoints now use unified minute replay runtime (with compatibility fallback):
  - `GET /api/top-pairs`
  - `GET /api/signals`
  - `GET /api/backtests`
  - `GET /api/spread-series`
- `POST /api/signals/refresh` now supports unified refresh path:
  - computes snapshot via minute replay,
  - persists `signal_run` + `signal_history`,
  - returns `engine=unified_minute_replay`.
- Added UI runtime settings:
  - `ui.use_unified_signal_engine`
  - `ui.unified_allow_legacy_fallback`
  - `ui.unified_snapshot_ttl_sec`
  - `ui.unified_pair_workers`
  - `ui.unified_front_only`
  - `ui.unified_front_roll_days`
- Default config switched to unified runtime in `configs/default.yaml`.

Added
- New module:
  - `src/moex_carry/ui/unified_runtime.py`
  - front-pair selection, replay cache, unified snapshot building, spread-series building.

Tests
- Added unified runtime/API tests:
  - `tests/test_ui_unified_runtime.py`.
- Re-ran compatibility/regression suite:
  - `tests/test_ui_api.py`
  - `tests/test_backtest_forward_api.py`
  - `tests/test_signal_replay_core.py`
  - `tests/test_signal_replay_golden_parity.py`

## 2026-02-12 - Unified Minute-First Execution Model (Backtest v2)

Changed
- Added execution mode contract to backtest request:
  - `execution.mode` with values:
    - `INTRADAY_MINUTE` (default),
    - `DAILY_COMMON_MINUTE`,
    - `DAILY_EOD`,
    - `DAILY_NEXT_OPEN`.
  - `execution.price_source`,
  - `execution.common_minute_anchor`.
- Added minute execution controls in strategy contract:
  - `entry_price_tolerance_pct` (fallback),
  - `entry_stock_tolerance_pct`,
  - `entry_future_tolerance_pct`,
  - `entry_spread_tolerance_pct`,
  - `signal_cutoff_before_day_end_minutes`.
- Added business validation:
  - `strategy.execution_lag_minutes >= 20` in `INTRADAY_MINUTE`.
- Added warning behavior:
  - `common_minute_anchor` is ignored in `INTRADAY_MINUTE`.
- Added new `signal_replay` module:
  - canonical day cutoff,
  - split-tolerance execution band override,
  - minute replay wrapper around causal execution logic.
- Integrated minute execution quality overlay into `backtest_v2`:
  - auto-load minute series from preload cache / intraday series files,
  - compute fill-quality summary in minute mode.
- Added warm-cache memoization for minute fill-quality summary in `backtest_v2.runtime`
  to avoid repeated minute replay cost on identical requests.
- `/api/backtest/run` response is backward compatible and now includes optional:
  - `fill_quality_summary`,
  - `execution_model`.
- Updated UI Backtest tab to render:
  - execution model details,
  - minute fill-quality summary (when available).

Added
- Canonical spec doc:
  - `docs/architecture/modules/minute-replay-canon-v1.md`.

Tests
- Added replay-core tests:
  - `tests/test_signal_replay_core.py`.
- Added golden parity test over 5 real minute fixtures:
  - `tests/test_signal_replay_golden_parity.py`.
- Extended resolver tests for minute constraints/warnings.
- Extended API test assertions for new optional backtest fields.

## 2026-02-11 - MOEX Connector VPN Fixes (Force Fallback + Candles Pagination)

Changed
- Added `moex.force_fallback` config (enabled in default config) to bypass primary host and route ISS requests directly via `moex.fallback_ips` for VPN environments.
- Extended fallback trigger logic in `MoexIssClient`:
  - fallback now activates not only on transport errors, but also on retryable HTTP statuses from primary path (`408`, `425`, `429`, `500`, `502`, `503`, `504`).
- Fixed `get_candles` pagination:
  - candles are now loaded page-by-page via `start/limit` (previously only first page could be read),
  - added duplicate-page guard to prevent infinite pagination loops when upstream ignores `start`.
- Updated all ad-hoc analysis scripts to use the same MOEX retry/fallback settings as the main pipeline.

Tests
- Added ISS client tests for:
  - fallback on retryable primary HTTP error,
  - force-fallback mode (primary skipped),
  - candles pagination (cursor-driven and start/limit fallback),
  - repeated-page pagination guard.

## 2026-02-10 - Causal Execution Replay (D+1) and Operational Annual Target

Changed
- Spread-series strategy replay switched to causal execution model:
  - signal on day `D`, earliest submit on `D+1`,
  - fill only on common executable timestamps for both legs,
  - configurable `execution_max_wait_minutes` timeout window.
- Added replay controls to `spread_carry_alpha` config:
  - `signal_exec_lag_days`,
  - `execution_lag_minutes`,
  - `execution_max_wait_minutes`,
  - `force_exit_policy`,
  - `force_exit_penalty_bps`,
  - `annual_target_threshold`.
- Added forced-exit handling for timeout scenarios (`next_anchor` / `market_worse`).
- Added operational execution lifecycle fields in spread series:
  - `entry_signal_day`, `entry_submit_ts`, `entry_fill_ts`, `entry_wait_minutes`,
  - `exit_signal_day`, `exit_submit_ts`, `exit_fill_ts`, `exit_wait_minutes`,
  - `entry_fill_status`, `exit_fill_status`, `exit_forced`, `unfilled_reason`.
- Added annual target metrics:
  - `trade_return_annual_fill_to_fill`,
  - `trade_return_annual_operational`,
  - `annual_target_threshold`,
  - `annual_target_pass`.
- Added aggregate execution-quality fields in top-pairs/signals:
  - `avg_trade_return_annual_operational_recent`,
  - `share_target_pass`,
  - `unfilled_entry_rate`,
  - `unfilled_exit_rate`,
  - `forced_exit_rate`.
- Updated UI formatting/metadata and spread chart summary to display operational annual results and target pass.

Tests
- Added replay tests:
  - `tests/test_execution_replay.py::test_replay_is_causal_d_plus_one_for_entry_and_exit`,
  - `tests/test_execution_replay.py::test_replay_marks_entry_unfilled_when_timeout_expires`,
  - `tests/test_execution_replay.py::test_replay_forces_exit_after_timeout_when_policy_enabled`.

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

