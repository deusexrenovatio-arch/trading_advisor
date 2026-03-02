# Session Handoff
Updated: 2026-03-02 19:20 UTC

## Goal
- Integrate the two-layer intraday signal-engine specification into the existing backend strategy architecture without breaking current contracts.

## Current Delta
- Added layered signal engine modules under `src/moex_carry/signal_engine/`.
- Added proposal->forecast->cost->gate orchestration in `src/moex_carry/signal_engine/engine.py`.
- Added adapters in `src/moex_carry/signal_engine/adapter.py` and `src/moex_carry/strategy/two_layer_adapter.py`.
- Added typed `signal_engine` config and defaults, including `runtime_adapter` feature flag.
- Wired runtime adapter into `compute_pairs`, `run_signal_cycle`, and unified snapshot/backfill flows.
- Runtime adapter keeps legacy fields in `signal_*_legacy` and writes two-layer data to `signal_metrics.two_layer`.
- Added deterministic unit tests for signal engine math and runtime wiring.
- Updated architecture docs in `docs/architecture/modules/backend-core.md` and `docs/architecture/modules/strategy-signal-interface.md`.

## Blockers
- None.

## Next Step
- Decide rollout mode for `signal_engine.runtime_adapter.enabled` in env-specific overrides (keep `false` by default).
- Add parity checks for unified `top_pairs`/`signals` action consistency when runtime adapter override is enabled.

## Validation
- `PYTHONPATH=src pytest tests/test_signal_engine_adapter.py tests/test_signal_engine_cost.py tests/test_signal_engine_gate.py tests/test_signal_engine_orb.py tests/test_signal_engine_probability.py tests/test_signal_engine_triple_barrier.py tests/test_signal_engine_vwap.py tests/test_config_loading.py tests/test_signal_cycle.py::test_run_signal_cycle_two_layer_runtime_adapter_overrides_legacy_fields -q`
- `python scripts/run_lean_gate.py`
- `python scripts/validate_quality_scorecards.py`
