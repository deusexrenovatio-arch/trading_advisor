# Minute-First Acceptance (2026-02-12)

## Scope
- Unified minute-first execution contract in `backtest_v2`.
- Canonical replay behavior from `intraday_*` logic.
- API/UI backward compatibility.

## Checklist

### 1) Unit tests (replay core)
- `submit/fill` timeline: covered by legacy replay tests (`tests/test_execution_replay.py`) and parity checks.
- `timeout/forced exit`: covered by `tests/test_execution_replay.py`.
- `split tolerance + fallback`: covered by `tests/test_signal_replay_core.py`.
- `cutoff behavior`: covered by `tests/test_signal_replay_core.py`.
- `sign-sensitive PnL`: covered by `tests/test_signal_replay_core.py`.

### 2) Golden parity (5 pairs, offline fixtures)
- Added fixtures (no network):
  - `tests/fixtures/minute_replay/AFLT_AFH6.csv`
  - `tests/fixtures/minute_replay/ALRS_ALH6.csv`
  - `tests/fixtures/minute_replay/CBOM_CMH6.csv`
  - `tests/fixtures/minute_replay/CHMF_CHH6.csv`
  - `tests/fixtures/minute_replay/FLOT_FLH6.csv`
- Added parity test:
  - `tests/test_signal_replay_golden_parity.py`
- Validates:
  - event track parity (`signal_action`, fill statuses/timestamps/waits, forced/unfilled fields),
  - key metrics parity vs script baseline (`intraday_minute_sweep`).

### 3) Integration API/UI
- Backward compatible `/api/backtest/run` payload: covered by `tests/test_backtest_forward_api.py`.
- Minute optional response fields present:
  - `fill_quality_summary`
  - `execution_model`
- UI:
  - renders both fields in Backtest tab (`ui-web/src/features/backtest-run/BacktestV2Tab.tsx`),
  - lint/build pass.

### 4) HPO/Forward integration
- HPO request with `execution.mode=INTRADAY_MINUTE` accepted: `tests/test_backtest_forward_api.py`.
- Forward start with same mode accepted: `tests/test_backtest_forward_api.py`.

### 5) Performance gates (measured)
- Local benchmark (25 pairs, `2025-09-24..2026-02-11`, warm cache):
  - `DAILY_EOD warm`: `0.69s`
  - `INTRADAY_MINUTE warm`: `0.66s`
  - Gate `minute <= 2x daily`: PASS.
- Cold run for 25 pairs / 1 scenario:
  - `INTRADAY_MINUTE cold`: `55.97s`
  - Gate `<= 60s`: PASS on this reference profile.
- Added runtime warm-cache memoization for minute fill quality to stabilize warm performance.

### 6) Architecture and stack gates
- High-load compute policy:
  - boundary I/O can use DataFrame utilities,
  - numeric hot paths are `numpy`-first,
  - `numba` is optional for profiled kernels with deterministic fallback.
- Canonical hot paths:
  - vectorized matrices/scoring in `src/moex_carry/backtest_v2/batch.py`,
  - optional Numba alpha kernels in `src/moex_carry/analytics/alpha.py`.
- Validation:
  - replay/parity tests remain mandatory (`tests/test_execution_replay.py`, `tests/test_signal_replay_core.py`, `tests/test_signal_replay_golden_parity.py`),
  - stack policy guard test: `tests/backtest_v2/test_compute_stack_policy.py`.
