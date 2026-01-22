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
  - `strategy`: z-score thresholds and carry parameters.
  - `aggregation`: weights, confidence threshold, and rebalance cadence.
  - `data`: data directory and lookback windows.
  - `environment`: mode, venue, timezone.
  - `risk_profile`: limits used by `risk_gate`.
  - `news_filter`: severity thresholds and sources list.
  - `ui`: Dash UI host/port.

### Loading and overrides
- File: `src/moex_carry/config.py`
- `load_settings` merges YAML overrides into default settings.
- Environment variables can override settings via `MOEX_CARRY__` prefix.

## Compatibility rules
- Contracts are the source of truth for decision outputs and UI projections.
- Configuration defaults must keep the pipeline deterministic and reproducible.
