# Minute Replay Canon v1

## Purpose
Single canonical execution model for spread strategy backtests in minute mode, based on `intraday_*` test scripts.

## Canonical Inputs
- Common stock/future minutes joined by exact `ts` inside each day.
- Strategy controls:
  - `signal_exec_lag_days`
  - `execution_lag_minutes`
  - `execution_max_wait_minutes`
  - `signal_cutoff_before_day_end_minutes`
  - `entry_price_tolerance_pct` + split tolerance overrides:
    - `entry_stock_tolerance_pct`
    - `entry_future_tolerance_pct`
    - `entry_spread_tolerance_pct`

## Canonical Semantics
- In `INTRADAY_MINUTE`, all common minutes of day are used.
- `common_minute_anchor` is ignored in minute mode.
- Submit/fill is causal:
  - signal at `signal_ts`,
  - submit after lag (`signal_exec_lag_days`, `execution_lag_minutes`),
  - fill only when tolerance bands are satisfied in shared minute stream.
- Timeout marks:
  - `entry_unfilled`,
  - `exit_unfilled`,
  - `forced` exit on timeout according to policy.
- Day cutoff removes late minutes before replay.

## Required Outputs
- Event/timing fields:
  - `entry_signal_day`, `entry_submit_ts`, `entry_fill_ts`, `entry_wait_minutes`
  - `exit_signal_day`, `exit_submit_ts`, `exit_fill_ts`, `exit_wait_minutes`
  - `entry_fill_status`, `exit_fill_status`, `exit_forced`, `unfilled_reason`
- Fill quality metrics:
  - `unfilled_entry_rate`
  - `unfilled_exit_rate`
  - `forced_exit_rate`
  - `share_target_pass`
- Sign-sensitive PnL: adverse leg movement must reduce trade PnL.

## Runtime Contract
- `execution.mode`:
  - `INTRADAY_MINUTE` (default)
  - `DAILY_COMMON_MINUTE`
  - `DAILY_EOD`
  - `DAILY_NEXT_OPEN`
- API response includes optional:
  - `fill_quality_summary`
  - `execution_model`

## Invariants Checklist
- Deterministic replay for same data/config.
- No look-ahead in submit/fill timestamps.
- Minute mode enforces `execution_lag_minutes >= 20`.
- Split tolerance falls back to `entry_price_tolerance_pct` per missing leg.
- Cutoff `> 0` reduces executable minute set before replay.

## Compute Architecture Guardrails
- Keep replay semantics independent from storage/transport details.
- Keep hot-path kernels vectorized where possible (`numpy`/`numba`) and avoid row-wise DataFrame loops.
- Keep cache/precompute logic in runtime/orchestration layer, not inside semantic replay rules.
- Any performance rewrite must preserve all invariants above and parity tests on minute fixtures.
