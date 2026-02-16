# Minute Refresh Default Plan

## Status
- Implemented on `chore/minute-refresh-default-plan` in `D:/wt-minute-refresh-plan`.
- Current default behavior: scheduled backend refresh every 60 seconds with incremental replay.

## Implemented decisions
- Scheduler defaults:
  - `ui.signal_refresh_interval_sec: 60`
  - `ui.signal_refresh_daily_time: null`
- Scheduled refresh path: `force=False` (incremental/non-force).
- Manual refresh path: `POST /api/signals/refresh` with `force=True` (forced full fallback).
- Startup mode: Cold+ThenInc.
- Overlap window: 180 minutes.
- Replay state durability: disk checkpoints.
- Nightly forced rebuild: disabled by default.

## Data/replay architecture
- Incremental minute ingest:
  - module: `src/moex_carry/minute_ingest/`
  - overlap polling, dedup by `exec_ts`, watermark update.
- True incremental replay:
  - module: `src/moex_carry/signal_replay/incremental.py`
  - per-pair checkpoints + replay state resume.
- Stateful replay step support:
  - `pipeline._apply_spread_carry_signals(...)` supports `initial_state`/`return_state`.

## Storage contracts
- Replay checkpoints:
  - `data/state/incremental_replay/<pair_id>/latest.json`
  - `data/state/incremental_replay/<pair_id>/checkpoints/<ts>.json`
- Incremental replay output:
  - `data/output/incremental_replay/<pair_id>.parquet`
  - if parquet engine is unavailable in runtime, pickle fallback can be used under the same path.

## Runtime/API behavior
- `GET /api/signals/refresh-status` includes:
  - `incremental_enabled`
  - `data_watermark_before`
  - `data_watermark_after`
  - `pairs_total`
  - `pairs_recomputed`
  - `pairs_reused`
  - `pairs_skipped`
  - `skip_reason`
- Degraded mode:
  - if minute ingest fails, service keeps last-good snapshot and marks refresh state as `degraded`.

## UI/read path
- Default API read path serves latest backend-produced output (last-good) for:
  - `/api/top-pairs`
  - `/api/signals`
  - `/api/backtests`
- Optional `fresh=1` enables on-demand in-process snapshot path.

## Validation
- Incremental replay tests:
  - `tests/test_signal_replay_incremental.py`
- Core parity/regression:
  - `tests/test_execution_replay.py`
  - `tests/test_signal_replay_core.py`
  - `tests/test_signal_replay_golden_parity.py`
  - `tests/test_ui_unified_runtime.py`
