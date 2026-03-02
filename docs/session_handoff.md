# Session Handoff
Updated: 2026-03-02 23:12 UTC

## Goal
- Implement the new main TZ as a futures-first morning planning pipeline (`D1/H1/M5 -> regime -> levels -> execution -> setups`) inside existing `signal_engine` architecture.

## Current Delta
- Added `POST /api/v2/research/morning-plan` in `src/moex_carry/ui/app.py` with futures ISS defaults (`engine_futures`, `market_futures`, `futures_board`).
- Endpoint now builds `MarketCalendar` from `settings.signal_engine.morning_plan.calendar` and executes `MorningPlanBuilder` via `IssCandleProvider`.
- Added recursive JSON serializer in API layer for dataclass/enum/datetime payloads used by morning-plan response.
- Added API smoke test `test_v2_research_morning_plan_wrapper` in `tests/test_api_v2.py` with wrapper-style monkeypatching.
- Added provider integration-style tests in `tests/test_signal_engine_data_provider.py` for TF->ISS interval mapping and causal sort/filter/limit behavior.
- Extended contract surface with `/research/morning-plan` in `docs/contracts/api-v2.yaml` to keep app/contract parity gate green.
- Targeted tests and full lean governance gate are green on this delta.

## Blockers
- None.

## Next Step
- Run a causal walk-forward historical check for commodity futures morning-plan setups (no look-ahead), with explicit calibration points and comparison slices.

## Validation
- `PYTHONPATH=src pytest tests/test_api_v2.py tests/test_signal_engine_data_provider.py -q`
- `python scripts/run_lean_gate.py`
