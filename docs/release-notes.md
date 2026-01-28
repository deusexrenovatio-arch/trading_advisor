# Release Notes

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

