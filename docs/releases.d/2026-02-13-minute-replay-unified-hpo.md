# Minute Replay Canon In Runtime/HPO

- Moved minute replay execution logic into `src/moex_carry/signal_replay/minute_replay.py` and rewired `signal_replay.core` to remove direct imports from `pipeline`.
- Added import-boundary regression tests in `tests/architecture/test_import_boundaries.py` to prevent `hpo -> pipeline` and `signal_replay.core -> pipeline` coupling.
- Extended execution contract with `execution.execution_model` (`MINUTE_REPLAY` / `DAILY_V2`) and `execution.minute_fail_fast`.
- Added minute period-PnL objective path for HPO in `src/moex_carry/hpo/minute_period_pnl.py` and wired `hpo.runner` to use it when `execution_model=MINUTE_REPLAY`.
- Added `/api/backtest/run` response field `parity_signature` and expanded execution metadata.
- Added optional `execution_quality` object to Top Pairs / Signals API rows.
- Added perf regression gate `tests/perf/test_minute_runtime.py` and CI job `perf-minute-runtime`; added non-blocking dependency audit job.
