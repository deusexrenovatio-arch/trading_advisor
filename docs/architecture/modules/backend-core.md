# Backend Core Modules

## Scope
This document covers the Python core in `src/moex_carry`, including orchestration,
strategies, storage, and the Flask API used by the UI. Dash UI is deprecated,
but the API endpoints remain the primary backend interface for the React app.

## Entry points
- `src/moex_carry/__main__.py`: entry point that delegates to the CLI.
- `src/moex_carry/cli.py`: commands for `fetch`, `compute`, `backtest`, `paper`,
  `signals`, `ui`, `history`, `backtest_v2`, `forward_start`, and `forward_status`.

## Orchestration
- `src/moex_carry/pipeline.py`
  - `fetch_data`: ingestion for MOEX ISS + CBR inputs.
  - `compute_pairs`: ranking and signal generation for stock-future pairs.
  - `run_backtest`: historical replay with output metrics.
  - `run_paper_trading`: builds `decision_log` + `decision_view`.
  - `run_signal_cycle`: live signal cycle and persistence.
  - `build_spread_series`: time series for UI charting.
- `src/moex_carry/forward/`
  - `ForwardTestEngine`: stateful EOD -> OPEN -> after-close paper loop.
  - `PaperBroker`: submit/simulate/apply fills without a real broker.
  - `JsonStateStore`: persistence for state, trades, equity, and alerts.

## Module catalog

### `analytics/`
- Responsibilities: carry/rate calculations and spread statistics.
- Key files: `carry.py`, `rates.py`, `stats.py`, `time.py`, `alpha.py` (new).
- Outputs: derived metrics used by strategies and ranking.
- Notes: alpha matrix helpers can use optional numba acceleration for batch backtests.
- Stack policy: keep alpha kernels numeric (`numpy`/`numba`) and keep DataFrame work at boundaries.

### `data/`
- Responsibilities: data source adapters and normalization for MOEX ISS and CBR.
- Key files: `moex_iss.py`, `cbr_rates.py`, `providers.py`, `dividends.py`, `streaming.py`, `history_store.py`.
- Outputs: normalized data frames and cached responses for the pipeline.

### `domain/`
- Responsibilities: shared domain models for instruments, portfolio state, and decisions.
- Key files: `models.py`, `decision.py`, `portfolio.py`.
- Outputs: typed entities reused across pipeline, storage, and contracts.

### `execution/`
- Responsibilities: execution model primitives (price mode, slippage, tick sizes).
- Key files: `model.py`.
- Outputs: execution parameters consumed by snapshot building and backtest/forward engines.

### `snapshot/`
- Responsibilities: assemble `SnapshotPerPair` with spreads, floor, liquidity, and costs.
- Key files: `builder.py`.
- Outputs: snapshot universe for backtest v2 and forward engines.

### `portfolio/`
- Responsibilities: allocation math and rebalance controller for target positions.
- Key files: `allocation.py`, `contracts.py`, `rebalance_controller.py`, `turnover.py`.
- Outputs: target positions, rebalance actions, turnover caps.

### `selection/`
- Responsibilities: instrument universe, liquidity checks, and ranking.
- Key files: `universe.py`, `liquidity.py`, `ranking.py`.
- Outputs: ranked pairs and candidate lists for strategy evaluation.

### `strategy/`
- Responsibilities: core signal logic and gating.
- Key files:
  - `spread_carry_alpha.py`: StockFuturesSpreadCarryAlpha entry/exit rules (primary).
  - `stat_signal.py`: legacy z-score entry/exit (deprecated after alpha rollout).
  - `carry_signal.py`: legacy implied rate carry logic (deprecated after alpha rollout).
  - `event_filters.py`: expiry/ex-dividend gating.
  - `orchestrator.py`: emits the module `SignalDecision` for downstream aggregation.
  - `risk_gate.py`: deterministic risk checks.
  - `news_filter.py`: deterministic news gating.
  - `overall_strategy.py`: hybrid aggregation of module signals.
  - `strategy_signal.py`: normalized strategy signal contract for aggregation.
  - `spread_adapter.py`: stub adapter for spread module integration.
- Outputs: `SignalDecision`, portfolio intents, and risk/news gate results.

### `costs/`
- Responsibilities: commission/slippage calculations and tax handling.
- Key files: `engine.py`, `taxes.py`.
- Outputs: cost model fields used in decision logs and backtests.

### `backtest/`
- Responsibilities: historical replay and walk-forward reporting.
- Key files: `engine.py`, `report.py`, `walk_forward.py`.
- Outputs: backtest metrics persisted in CSV and decision logs.

### `backtest_v2/`
- Responsibilities: multi-pair backtest engine isolated from legacy backtest.
- Key files:
  - `engine.py` (run_backtest_v2 + precompute),
  - `batch.py` (feature/alpha matrices + batch scoring),
  - `runtime.py` (history-backed runner + precompute cache),
  - `minute_portfolio_engine.py` (minute replay tapes + portfolio-level execution simulation).
- Outputs: `BacktestReport` with equity curve, trades, and summary metrics.
- Notes: uses SnapshotBuilder + PortfolioRebalanceController; optional fast alpha cache when precomputed data is supplied.
- Annualization: metrics respect `rates.use_trading_days` (252 vs 365) for ExcessAnn, Vol_ann, IR, Sharpe.
- Minute portfolio path:
  - exit-first event priority,
  - entry only on `entry_filled` events from minute replay,
  - explicit idle/unfilled/forced portfolio metrics.
- Stack policy: `batch.py` is the canonical vectorized hot path and should remain `numpy`-first.

### `hpo/`
- Responsibilities: hyperparameter search on top of Backtest v2 (black-box), walk-forward splits with embargo,
  objective/constraints, aggregation, and sampling strategies.
- Key files: `search_space.py`, `folds.py`, `objective.py`, `runner.py`, `runtime.py` (async run/status).
- Outputs: trial results, leaderboard, and best config selection.
- Persistence: `data/hpo/runs/<run_id>/status.json` and `result.json` for async runs.
- Objective: supports `optimization.metric` + `optimization.mode` (max/min) and applies
  penalty constraints for MaxDD/AvgTurnover when configured.
- Portfolio objective path:
  - `scope=PORTFOLIO` uses minute portfolio evaluation (`compute_minute_portfolio_window_metrics`)
    for both val/test windows.
  - Trial payload includes `evaluation_scope` and `objective_breakdown`
    for auditability of penalties and gate outcomes.

### `forward/`
- Responsibilities: forward paper execution loop with state persistence.
- Key files: `engine.py`, `broker.py`, `store.py`, `interfaces.py`, `runtime.py`.
- Outputs: persisted state (`state.json`), trades/equity/alerts JSONL streams.
- Notes: wired to API/CLI via history-backed runtime adapter.

### `storage/`
- Responsibilities: database access and persistence of signals/executions.
- Key files: `db.py`, `models.py`, `repositories.py`.
- Outputs: SQLite tables for signals, executions, and backtests.

### `decision_log.py`
- Responsibilities: schema validation and projection to `decision_view`.
- Inputs: decision payload from the pipeline.
- Outputs: `decision_log.jsonl` and `decision_view.jsonl`.

### `history.py`
- Responsibilities: incremental historical candles download with state tracking.
- Outputs: historical CSV files under `data/history/`.

### `minute_ingest/`
- Responsibilities: incremental minute-candle ingestion with overlap window, upsert/dedup, watermark tracking.
- Key files: `cursor_state.py`, `store.py`, `runner.py`.
- Outputs:
  - updated pair minute series under `data/output/intraday_minute_series/`,
  - cursor/watermark state under `data/state/incremental_replay/<pair_id>/cursor.json`.

### `signal_replay/`
- Responsibilities: minute replay execution core and true incremental replay/checkpoint engine.
- Key files: `core.py`, `minute_loader.py`, `incremental.py`.
- Outputs:
  - per-pair replay output under `data/output/incremental_replay/<pair_id>.parquet`,
  - latest and periodic checkpoints under `data/state/incremental_replay/<pair_id>/`.

### `broker/`
- Responsibilities: adapter boundary for execution and broker integration.
- Key files: `adapter.py` (abstraction for order flow).

### `logging.py`
- Responsibilities: logging configuration and formatting.

### `ui/`
- Responsibilities: Flask API endpoints for the React UI (Dash UI deprecated).
- Key files:
  - `app.py`: API composition root and route wiring (Dash layout still present but not used in production).
  - `data.py`: loaders for CSV/JSONL artifacts.
  - `decision_actions.py`: decision action service (`/api/v2/decisions/*/actions`) and idempotent JSONL projection writes.
  - `refresh_scheduler.py`: background refresh loop with multi-worker singleton lease behavior.
  - `routes_market_data.py`: signal history/executions, backtests, portfolio rebalance, and spread-series route group.
  - `routes_ops.py`: operational health/SLO endpoints (`/api/v2/ops/health`, `/api/v2/ops/slo`).
  - `routes_pretrade.py`: pretrade check endpoints (`/api/pretrade/check`, `/api/v2/pretrade/check`).
  - `routes_research.py`: research wrappers (`/api/v2/research/backtests/run`, `/api/v2/research/hpo/run`, `/api/v2/research/hpo/status`).
  - Signal refresh scheduler (configurable in `ui.signal_refresh_*` and incremental settings).
  - Scheduled refresh uses non-force incremental path.
  - Manual refresh endpoint uses forced full path.
  - Refresh endpoints: `POST /api/signals/refresh`, `GET /api/signals/refresh-status`.
  - Backtest/forward endpoints: `POST /api/backtest/run`, `POST /api/forward/start`, `GET /api/forward/status`.
  - HPO endpoints: `POST /api/hpo/run` (async start), `GET /api/hpo/status` (status + result).
  - V2 endpoints:
    - `GET /api/v2/signals/active`, `POST /api/v2/signals/<signal_id>/actions`
    - `GET /api/v2/decisions/view`
    - `GET /api/v2/news/feed`
    - `POST /api/v2/research/backtests/run`, `POST /api/v2/research/hpo/run`, `GET /api/v2/research/hpo/status`
    - `GET /api/v2/portfolio/rebalance/preview`, `POST /api/v2/portfolio/rebalance/commit`

## Parallel dev workflow
- Run backend API: `python -m moex_carry.cli ui` (serves `/api/*` on `127.0.0.1:8050`).
- Run React UI: `npm run dev` from `ui-web/` (Vite proxies `/api` to `127.0.0.1:8050`).
- This allows backend and frontend development in parallel with independent reloads.

## Persistence outputs
- CSV artifacts: `data/output/top_pairs.csv`, `data/output/signals.csv`,
  `data/output/backtest_summary.csv`.
- Decision logs: `data/decisions/decision_log.jsonl`,
  `data/decisions/decision_view.jsonl`.
- Database: SQLite at `data/moex_carry.db` with tables from `storage/models.py`.

## Contracts and dependencies
- Schemas: `contracts/decision-log.schema.json`,
  `contracts/decision-view.schema.json`.
- Config defaults: `configs/default.yaml`, loaded by `config.py`.
