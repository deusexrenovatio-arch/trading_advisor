# Signal Engine Spec Addendum v1.1

Updated: 2026-03-02

## Scope
This document is a normative addendum to the original two-layer signal-engine specification.
It closes ambiguity that can cause non-deterministic behavior, live/backtest drift, or hidden risk.

The base requirement remains unchanged:
- Layer 1: candidate trade generation (`AlphaProposal`).
- Layer 2: outcome probabilities + gating (`OutcomeForecast` -> actionable/advisory/no-trade).

## Added Requirements (Normative)

### 1) Session and clearing calendar contract
- Calendar resolution must be centralized in one adapter and must not be hardcoded inside strategy logic.
- `MarketRegimeFlags` must be derived from the same calendar source for backtest and live paths.
- If calendar state is unavailable, system must fail conservative:
  - no new entries,
  - advisory allowed,
  - metadata reason: `calendar_unavailable`.

### 2) Instrument spec source and fallback policy
- `tick_size` and `multiplier` must come from a single source of truth (instrument spec registry).
- Missing or invalid spec must fail conservative:
  - no actionable signal,
  - metadata reason: `instrument_spec_missing_or_invalid`.
- TP/SL/cost/PNL calculations must not run on float price units without validated tick spec.

### 3) Unified execution-price semantics
- Entry/exit price source must be explicitly declared per mode:
  - live: executable side (`bid/ask`) when available,
  - replay/backtest: deterministic OHLC policy with fixed tie-break rules.
- Execution lag semantics must be identical between live and replay for the same mode configuration.

### 4) Regime key canonicalization
- Probability context key must be canonicalized and versioned:
  - `(strategy_id, instrument_group, vol_regime, session_part, key_version)`.
- `vol_regime` and `session_part` definitions must be shared between probability estimation and gate logic.

### 5) Historical outcomes source contract
- Runtime probability layer must declare source of historical outcomes:
  - real realized outcomes when available,
  - synthetic fallback only when explicit and flagged in metadata.
- Cold start behavior must be conservative:
  - Dirichlet prior allowed,
  - tier must not escalate without sufficient `n_effective`.

### 6) Calibration lifecycle
- Post-hoc calibration is mandatory when enough data is available.
- Calibration must define:
  - train window,
  - refresh cadence,
  - minimum sample thresholds,
  - fallback path when thresholds are not met.
- Every calibrated forecast must include calibration provenance in metadata.

### 7) Orderbook-missing behavior
- If orderbook data is unavailable, behavior must be mode-configurable and explicit:
  - `block`,
  - `advisory_only`,
  - `allow_with_penalty`.
- Default is conservative (`advisory_only` or stricter).

### 8) Persistence/API compatibility contract
- New two-layer fields must be additive for CSV/DB/API outputs.
- Existing consumers must remain functional with legacy fields.
- If overriding legacy fields is enabled, original values must be preserved in explicit `*_legacy` fields.

### 9) Probability quality SLO/KPI
- The module must define and track quality KPIs:
  - Brier score,
  - logloss,
  - reliability (calibration error),
  - drift indicators.
- Actionability policy must support automatic degradation to advisory/no-trade on sustained KPI breach.

### 10) Transport/data-gap fail-safe
- ISS/data transport failures must not silently promote actionable trades.
- Degraded data mode must be explicit in metadata and telemetry.
- Retry exhaustion must produce deterministic fallback (no action escalation).

### 11) Environment rollout policy
- `runtime_adapter` rollout must be environment-scoped and documented:
  - `dev` -> `stage` -> `prod`.
- Default config remains conservative (`enabled: false`) until explicit promotion criteria are met.
- Recommended override profiles:
  - Shadow mode: `configs/overrides/runtime_adapter_shadow.yaml` (`enabled: true`, `override_signal_fields: false`).
  - Actionable mode: `configs/overrides/runtime_adapter_actionable.yaml` (`enabled: true`, `override_signal_fields: true`).
- Launch examples:
  - `python -m moex_carry.cli signals --config configs/overrides/runtime_adapter_shadow.yaml`
  - `python -m moex_carry.cli signals --config configs/overrides/runtime_adapter_actionable.yaml`

### 12) Legacy strategy migration protocol
- Migration of legacy strategies to two-layer runtime must use a staged parity process:
  - shadow mode,
  - parity checks on actions/reasons,
  - controlled override enablement.
- Each migration step must define rollback criteria.

## Acceptance Additions
- Add regression tests for:
  - calendar unavailable fail-closed entry behavior,
  - instrument spec missing fail-closed behavior,
  - live/backtest execution-price parity under same policy,
  - synthetic-history metadata flagging,
  - override compatibility (`signal_*` + `signal_*_legacy` coexistence),
  - KPI-triggered degradation to advisory/no-trade.

## Current Repository Mapping
- Two-layer core exists under `src/moex_carry/signal_engine/`.
- Runtime bridge exists in `src/moex_carry/strategy/two_layer_adapter.py`.
- Runtime wiring entry points:
  - `src/moex_carry/pipeline.py` (`compute_pairs`, `run_signal_cycle`, `backfill_signal_history`).
- Config surface:
  - `src/moex_carry/config.py` (`signal_engine.*`, `signal_engine.runtime_adapter.*`),
  - `configs/default.yaml`.

## Change Control
- Any change to these requirements must update:
  - this addendum,
  - related module docs,
  - tests and gate checks that enforce the behavior.
