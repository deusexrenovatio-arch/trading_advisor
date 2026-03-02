# Session Handoff
Updated: 2026-03-02 22:35 UTC

## Goal
- Implement the new main TZ as a futures-first morning planning pipeline (`D1/H1/M5 -> regime -> levels -> execution -> setups`) inside existing `signal_engine` architecture.

## Current Delta
- Added morning-plan core contracts in `src/moex_carry/signal_engine/core/types.py` (TF/regime/level/order/setup/plan dataclasses and enums).
- Added config-driven `MarketCalendar` in `src/moex_carry/signal_engine/core/calendar.py` (sessions, clearing, forbid windows, expiry policy).
- Added OHLCV utility layer in `src/moex_carry/signal_engine/core/ohlcv.py` (`resample_ohlcv`, EMA/ATR/ADX/ER/percentile).
- Added data-provider layer in `src/moex_carry/signal_engine/data/` (`DataProvider`, ISS provider, in-memory provider).
- Added engines: `RegimeEngine`, `LevelEngine`, `ExecutionEngine`, `SetupGenerator`, `MorningPlanBuilder`.
- Extended settings contracts in `src/moex_carry/config.py` and defaults in `configs/default.yaml` with `signal_engine.morning_plan`.
- Added deterministic tests for regime/levels/execution/setups/plan + config section coverage.
- Targeted test suite and lean governance gate pass on current patch set.

## Blockers
- None.

## Next Step
- Wire a runtime entrypoint (CLI/API) for morning plan generation and add JSON contract tests for plan payload shape and determinism across repeated runs.

## Validation
- `PYTHONPATH=src pytest tests/test_signal_engine_regime.py tests/test_signal_engine_levels.py tests/test_signal_engine_execution.py tests/test_signal_engine_setups.py tests/test_signal_engine_morning_plan.py tests/test_config_loading.py -q`
- `python scripts/run_lean_gate.py`
