# Compute Stack Architecture (Minute Workloads)

## 1) Objective
Make high-load minute-candle workloads fast and maintainable from the first implementation, not by late rewrites.

## 2) Layered model
- `Layer A: Ingestion and normalization`
  - Responsibilities: API calls, chunking, schema cleanup, joins by timestamp.
  - Preferred tools: `requests`, `pandas` (boundary only), typed configs.
- `Layer B: Numeric kernels`
  - Responsibilities: scoring, alpha/probability math, windowed transforms, penalties.
  - Preferred tools: `numpy` arrays first, `numba` for CPU-hot inner loops.
  - Rule: no row-wise DataFrame operations in this layer.
- `Layer C: Orchestration and scaling`
  - Responsibilities: shard strategy, worker topology, retries, cache mode, artifact merge.
  - Preferred tools: subprocess/thread pools, deterministic merge and ordering.

## 3) Stack decision table
- Use `pandas` when:
  - reading/writing tabular artifacts,
  - one-time alignment/cleanup at boundaries,
  - producing operator-facing summaries.
- Use `numpy` when:
  - running repeated math over dense numeric matrices,
  - scoring over `days x pairs` grids,
  - slicing windows for many scenarios.
- Use `numba` when:
  - profiler shows repeated Python-loop CPU hotspots,
  - kernel has numeric, typed loops with stable control flow,
  - parity tests already exist for fallback behavior.

## 4) Coding rules for hot paths
- Convert data to arrays once per stage; reuse arrays downstream.
- Keep memory layout predictable (`float64`/`bool` where possible).
- Avoid per-iteration object creation inside nested loops.
- Keep side effects out of kernels (pure input -> output functions).
- Keep fallback path and compare outputs in tests.

## 5) Review checklist (PR gate)
- Architecture:
  - Hot path placed in numeric layer (`numpy`/`numba`) rather than row-wise `pandas`.
  - Orchestration isolated from kernel logic.
  - If module boundaries/dependencies changed, run `architecture-review` checklist first.
- Correctness:
  - Replay invariants unchanged.
  - Parity tests pass for optimized vs fallback path.
- Performance:
  - Cold and warm benchmarks reported.
  - Cache mode and hardware profile explicitly stated.
