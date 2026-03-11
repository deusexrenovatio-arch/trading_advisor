# CTX-RESEARCH

## Scope
Backtest, replay, analytics, and HPO runtime/performance.

## Owned Paths
- `src/moex_carry/analytics/`
- `src/moex_carry/backtest/`
- `src/moex_carry/backtest_v2/`
- `src/moex_carry/broker/`
- `src/moex_carry/costs/`
- `src/moex_carry/execution/`
- `src/moex_carry/forward/`
- `src/moex_carry/hpo/`
- `src/moex_carry/perf.py`
- `src/moex_carry/signal_replay/`
- `src/moex_carry/snapshot/`

## Guarded Paths (do not change in this context)
- `src/moex_carry/ui/`
- `ui-web/`
- `src/moex_carry/storage/`
- `contracts/`

## Input/Output Contracts
- Input: strategy requests and snapshot universe.
- Output: `BacktestReport`, `HpoRun` status/results, replay artifacts.

## Invariants
- Preserve minute replay parity and deterministic behavior.
- Keep compute stack policy boundaries (`pandas` boundary, `numpy`/`numba` kernels).

## Minimum Checks
- `python scripts/run_loop_gate.py --from-git --git-ref HEAD`
- `pytest tests/perf -q`


