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
- `signal_refresh_enabled`: turn on periodic `run_signal_cycle` execution.
- `signal_refresh_interval_sec`: interval in seconds between refresh runs.
- `signal_refresh_daily_time`: optional local time (`HH:MM` or `HH:MM:SS`) for daily refresh.
- `signal_refresh_timezone`: optional IANA timezone for daily scheduling (defaults to `environment.timezone`).
- `signal_refresh_max_pairs`: optional max pairs override for refresh.
- `signal_refresh_save_csv`: persist refreshed CSV outputs when true.

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
  and `spread_history_days` (default 90) used by the alpha window.
- Validation and AUTO resolution live in `config_resolver.py`.

## Compatibility rules
- Contracts are the source of truth for decision outputs and UI projections.
- Configuration defaults must keep the pipeline deterministic and reproducible.
- CSV outputs (top pairs) add: `spread_pct`, `rtc_pct`, `floor_rate_annual`,
  `score_floor`, `score_alpha`, `total_score`, `decision`.
- UI tables surface floor + decision fields; alpha metrics are displayed in the
  pair details panel.
