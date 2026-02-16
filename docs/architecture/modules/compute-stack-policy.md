# Compute Stack Policy (High-Load Minute Workloads)

## Purpose
Define implementation rules for backtest/forward/HPO workloads that operate on large minute-candle histories (multi-year windows, multi-pair universes, scenario grids).

## Layered architecture
- `Boundary I/O layer`:
  - Source adapters, chunked loading, schema normalization, persistence.
  - `pandas` is allowed here for tabular interoperability.
- `Numeric kernel layer`:
  - Core math over dense grids: scoring, alpha matrices, penalties, objective metrics.
  - `numpy` is the default.
  - `numba` is allowed for proven CPU hotspots with maintained parity fallback.
- `Orchestration layer`:
  - Sharding, worker topology, cache policy, retries, artifact merge.
  - Keep independent from numerical kernel internals.

## Stack selection rules
- Prefer `numpy` when complexity grows with `days x pairs x scenarios`.
- Keep `pandas` out of inner loops and avoid row-wise operations in hot paths.
- Use `numba` only after profiling confirms hotspot concentration in pure numeric loops.
- Keep optimized and fallback paths behaviorally equivalent.

## Current repository examples
- Vectorized scoring and feature matrices:
  - `src/moex_carry/backtest_v2/batch.py`
- Optional Numba kernels with NumPy fallback:
  - `src/moex_carry/analytics/alpha.py`
- Runtime caching and deterministic reuse:
  - `src/moex_carry/backtest_v2/runtime.py`
- Sharded parallel orchestration:
  - `scripts/period_pnl_parallel_runner.py`

## PR gates
- Architecture gate:
  - No new row-wise DataFrame logic in numeric hot paths.
  - Separation between I/O, kernels, and orchestration is preserved.
- Correctness gate:
  - Replay invariants and parity tests pass.
- Performance gate:
  - Cold and warm measurements are reported with explicit cache mode and hardware profile.

## Anti-patterns
- DataFrame `.apply` inside nested day/pair/scenario loops.
- Repeated DataFrame <-> ndarray conversion inside hot loops.
- Blending API/network I/O directly into scoring kernel code.
- Shipping speedups without deterministic parity evidence.
