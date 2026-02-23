# Contracts and Configuration

## Scope
This document describes the stable contracts and configuration surface that the
pipeline, UI, and decision logging rely on.

## Contracts

### Decision Log
- File: `contracts/decision-log.schema.json`
- Purpose: canonical, immutable record for every decision.
- Required sections:
  - `environment`, `input_snapshots`, `feature_set`, `strategies`,
    `portfolio_proposal`, `risk_checks`, `cost_model`, `decision`.
- Compatibility:
  - `additionalProperties: false` enforces strict schema adherence.
  - Any new fields must be added explicitly and remain backward compatible.

### Decision View
- File: `contracts/decision-view.schema.json`
- Purpose: UI projection derived from `decision_log`.
- Required sections:
  - `decision_id`, `created_at`, `strategy_type`, `primary_instrument`,
    `action`, `risk_state`, `cost_summary`, `key_features`, `links`.
- Compatibility:
  - `additionalProperties: false` ensures UI expectations stay stable.
  - The view is derived only from `decision_log` fields.

## Configuration

### Default settings
- File: `configs/default.yaml`
- Major sections:
  - `moex`, `cbr`: upstream data source configuration.
  - `database`: SQLite connection and echo flag.
  - `costs`, `taxes`: commission and tax assumptions.
  - `strategy`: legacy z-score/carry parameters (deprecated after alpha rollout).
  - `spread_carry_alpha`: floor + alpha parameters for stock/futures spreads.
  - `aggregation`: weights, confidence threshold, and rebalance cadence.
  - `data`: data directory and lookback windows.
  - `environment`: mode, venue, timezone.
  - `risk_profile`: limits used by `risk_gate`.
  - `news_filter`: severity thresholds and sources list.
  - `ui`: API host/port plus optional signal refresh scheduler.

UI refresh keys:
- `signal_refresh_enabled`: enables backend scheduler for signal refresh.
- `signal_refresh_interval_sec`: interval in seconds between scheduled refresh runs (default `60`).
- `signal_refresh_singleton`: enforce single scheduler leader across multi-worker API processes.
- `signal_refresh_lease_sec`: lease TTL used by scheduler leader election.
- `signal_refresh_lease_renew_sec`: heartbeat interval for scheduler lease renewal.
- `signal_refresh_daily_time`: optional local time (`HH:MM` or `HH:MM:SS`) for daily refresh; default is `null` (disabled).
- `signal_refresh_timezone`: optional IANA timezone for daily scheduling (defaults to `environment.timezone`).
- `signal_refresh_max_pairs`: optional max pairs override for refresh.
- `signal_refresh_save_csv`: persist refreshed CSV outputs when true.
- `incremental_replay_enabled`: enable true incremental replay path (default `true`).
- `incremental_overlap_minutes`: overlap window for correction-safe replay (default `180`).
- `incremental_checkpoint_dir`: checkpoint root for per-pair replay state on disk.
- `incremental_checkpoint_interval_minutes`: periodic checkpoint cadence (default `60`).

Refresh behavior:
- Scheduled refresh (`signal_refresh_interval_sec`) runs non-force incremental path.
- Manual `POST /api/signals/refresh` runs forced full path (`force=True`) as fallback/recovery action.
- `GET /api/signals/refresh-status` exposes telemetry fields:
  - `incremental_enabled`, `data_watermark_before`, `data_watermark_after`,
  - `pairs_total`, `pairs_recomputed`, `pairs_reused`, `pairs_skipped`, `skip_reason`.

### SpreadCarryAlpha settings (new)
Expected parameters include (non-exhaustive):
- rates: `r_cb_annual`, `r_fund_annual`, `r_disc_annual` (defaults to r_cb_annual).
- execution: `slip_stock_bps`, `slip_fut_bps` or `slip_fut_ticks`.
- costs: `fee_stock_per_share` or `fee_stock_bps`, `fee_fut_per_contract`.
- floor: `floor_tolerance`, `riskbuffer_floor`, `capital_base_mode`.
- liquidity: bid/ask thresholds, dollar volume, open interest, days-to-exit.
- alpha: `H_list` or `H_max_days`, `TP_pct`, `SL_pct`, `z_entry_threshold`.
- portfolio: `max_gross_notional`, `max_contracts_per_pair`, `margin_proxy`.
- expiries: `allowed_expiry_months`, `allowed_expiry_years` (filters active contracts).

Defaults:
- `r_fund_annual` and `r_disc_annual` default to the latest CBR key rate.

### Loading and overrides
- File: `src/moex_carry/config.py`
- `load_settings` merges YAML overrides into default settings.
- Environment variables can override settings via `MOEX_CARRY__` prefix.

### Backtest request settings
- File: `src/moex_carry/contracts/strategy_test.py`
- `BacktestRequest` defines the backtest surface used by backtest v2.
- Notable strategy fields include `H_max_days`, `TP_pct`, `SL_pct`,
  `spread_history_days` (default 90), plus entry gates:
  `z_entry_threshold`, `min_floor_score`, `min_alpha_score`.
- Minute execution controls:
  - `execution.mode` (`INTRADAY_MINUTE`, `DAILY_COMMON_MINUTE`, `DAILY_EOD`, `DAILY_NEXT_OPEN`)
  - `execution.execution_model` (`MINUTE_REPLAY` | `DAILY_V2`)
  - `execution.minute_fail_fast` (missing minute series => hard fail in minute objective flow)
- Rebalance controls include:
  - `rebalance.cadence`
  - `rebalance.target_utilization`
- `rates.use_trading_days=true` switches annualization to 252 trading days
  for ExcessAnn/Vol_ann/IR/Sharpe metrics.
- Validation and AUTO resolution live in `config_resolver.py`.

### HPO request + async status
- File: `src/moex_carry/contracts/strategy_test.py`
- `HpoRequest` wraps `base: BacktestRequest`, `search_space`, and `cv/optimization` configs.
- Runtime endpoints:
  - `POST /api/hpo/run` starts async HPO and returns `run_id`, `status`, `progress`.
  - `GET /api/hpo/status?run_id=...` returns status and attaches `result` when completed.
- Optimization controls:
  - `optimization.metric`: objective metric (`excess_ann`, `cagr`, `ir`, `vol_ann`, `max_dd`,
    `avg_turnover`, `win_rate`, `profit_factor`, `avg_hold_days`, `share_alpha_exits`,
    `r_d`, `b_d`, `ex_d`, `sharpe`).
  - `optimization.mode`: `max` or `min` (direction for objective + leaderboard sorting).
  - `cv.test_size`: proportion of available days used for val/test sizing (val=test).
- Portfolio-first objective controls:
  - `optimization.scope` (`PORTFOLIO` default, `PAIR_MEAN` debug/benchmark mode)
  - `optimization.portfolio_metric` (`utility`, `excess_ann`, `cagr`)
- Trial result surface includes:
  - `evaluation_scope`
  - `objective_breakdown` (base metric + penalties + gate result diagnostics)
- Status payload (core fields):
  - `run_id`, `status` (running|completed|failed), `progress {completed,total}`,
    `created_at`, `started_at`, `finished_at`, optional `error`, `result`.

### API v2 surface
- File: `docs/contracts/api-v2.yaml`
- Adds contract-first surfaces for:
  - `signals/active` + `signals/{signal_id}/actions`
  - `decisions/view`
  - `news/feed`
  - `research/backtests/run`, `research/hpo/run`, `research/hpo/status`
  - `portfolio/rebalance/preview`, `portfolio/rebalance/commit`
- Write endpoints require `idempotency_key` (`signals/*/actions`, `decisions/*/actions`)
  to enforce at-most-once execution semantics.

## Compatibility rules
- Contracts are the source of truth for decision outputs and UI projections.
- Configuration defaults must keep the pipeline deterministic and reproducible.
- CSV outputs (top pairs) add: `spread_pct`, `rtc_pct`, `floor_rate_annual`,
  `score_floor`, `score_alpha`, `total_score`, `decision`.
- UI tables surface floor + decision fields; alpha metrics are displayed in the
  pair details panel.
