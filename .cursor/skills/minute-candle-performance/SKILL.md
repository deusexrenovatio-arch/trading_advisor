---
name: minute-candle-performance
description: "Performance engineering workflow for high-volume candle computations in this repository: minute-candle ingestion, replay acceleration, cache design, chunking, and deterministic parallelization across pairs/scenarios. Use when requests mention optimization, performance, speed-up, parallelization, multiprocessing, bottlenecks, large candle exports, minute candles, heavy backtest batches, preload cache, or runtime scaling (оптимизация, параллелизация, узкие места, минутные свечи, большие выгрузки)."
---

# Minute Candle Performance

## Overview
Use this skill to make minute-candle workloads fast by default: profile first, parallelize safely, minimize I/O, and preserve deterministic outputs.

## Coordination with architecture-review
- Use `architecture-review` together with this skill when changes touch module boundaries, dependencies, or ownership of compute responsibilities.
- Apply in order:
  1. `architecture-review`: verify boundaries and dependency direction.
  2. `minute-candle-performance`: choose stack and optimize kernels/orchestration inside approved boundaries.
- If architecture and performance goals conflict, keep boundary correctness first and then optimize within the chosen module boundary.

## Repository anchors
- Use `scripts/intraday_minute_sweep.py` for scenario grid replay and cache preparation.
- Use `scripts/prewarm_intraday_cache.py` to prime preload cache without replay.
- Use `scripts/period_pnl_parallel_runner.py` for sharded parallel runs over scenarios or pairs.
- Use `src/moex_carry/backtest_v2/runtime.py` for in-process precompute/fill-quality caches.
- Use `src/moex_carry/backtest_v2/batch.py` for vectorized batch scoring patterns.
- Use `src/moex_carry/analytics/alpha.py` for optional Numba kernels with NumPy fallback.
- Use `docs/architecture/modules/minute-replay-canon-v1.md` for canonical minute semantics and invariants.
- Use `docs/acceptance/minute-first-acceptance-2026-02-12.md` for current performance gates.
- Use `references/perf-playbook.md` for tuning matrix and reporting checklist.
- Use `references/stack-architecture.md` for stack selection policy by workload layer.

## Compute architecture and stack policy
- Build minute workloads as layered pipeline:
  - I/O and normalization layer: adapters, chunked fetch, schema cleanup.
  - Numeric kernel layer: dense arrays and vectorized math for core compute.
  - Orchestration layer: sharding, retries, cache policy, and artifact merge.
- Select stack by layer, not by convenience:
  - Use `pandas` only at ingestion and final reporting boundaries.
  - Use `numpy` as default for hot-path transforms and scoring.
  - Use `numba` for repeated inner kernels when profiler shows CPU bottleneck and kernels are numerically stable.
- Block anti-patterns in hot paths:
  - row-wise `DataFrame.apply`, per-row Python loops over candles, repeated object allocations inside day/pair loops.
  - mixing business rules and I/O in the same compute loop.
- Keep deterministic fallback:
  - every optimized kernel must keep behavior parity with pure-NumPy/Python fallback path.
  - no optimization is accepted without parity and replay-invariant checks.

## Workflow
1. Define performance target before changes:
- Select profile: cold-start latency, warm latency, throughput, or batch completion time.
- Freeze data window, pair set, and scenario grid for before/after comparability.
- Record hardware profile (CPU cores, RAM, storage type).

2. Prewarm and separate I/O from compute:
- Run cache warmup first to isolate compute bottlenecks from network/data fetch.
- Keep `preload_cache_mode` explicit (`readonly`, `readwrite`, or `refresh`).
- Tune `minute_chunk_days` to balance request overhead and memory footprint.

2.1. Choose implementation stack before coding:
- Estimate complexity axis early: `days x pairs x scenarios x feature_count`.
- If complexity is high and loops are numeric, implement directly in `numpy` (optionally `numba`) instead of starting from row-wise `pandas`.
- Keep `DataFrame -> ndarray` conversion at boundary once; avoid repeated conversions in hot loops.

3. Choose parallelization axis explicitly:
- Use shard-by-pair when scenario count is small and pair count is large.
- Use shard-by-scenario when scenario count is large and pairs are stable.
- Keep subprocess-level parallelism (`--jobs`) independent from in-shard workers (`--pair-workers`, `--preload-workers`).

4. Keep outputs deterministic:
- Use fixed pair/scenario lists and stable sort keys.
- Ensure every shard emits explicit CSV/JSON artifacts and merge deterministically.
- Block changes that improve speed but break replay invariants or parity tests.

5. Scale with cache-aware runtime:
- Use Backtest v2 `precompute` when compatible to avoid repeated snapshot builds.
- Respect config subset compatibility for precompute cache reuse.
- Reuse warm fill-quality summary for minute mode where applicable.

6. Validate performance and correctness together:
- Run performance probes and core regression tests in the same change.
- Check canonical minute replay invariants after optimization.
- Report both speed and behavior deltas; never ship speed-only evidence.

7. Enforce architecture gates in review:
- Confirm hot-path modules follow stack policy in `docs/architecture/modules/compute-stack-policy.md`.
- Add or update tests that protect stack boundaries and vectorized entrypoints.
- Update acceptance notes with cold/warm numbers, cache mode, and hardware profile.
- If module boundaries changed, run architectural checklist with `architecture-review` before accepting optimization changes.

## Core commands
```bash
python scripts/prewarm_intraday_cache.py --config configs/default.yaml --lookback-days 400 --preload-cache-mode readwrite --preload-workers 4 --minute-chunk-days 21
python scripts/period_pnl_parallel_runner.py --config configs/default.yaml --scenario-specs-file data/output/period_scenarios.txt --pairs-file data/output/front_pairs.txt --jobs 4 --pair-workers 1 --preload-workers 4 --minute-chunk-days 21 --preload-cache-mode readonly
python -m moex_carry.cli backtest_v2 --config configs/default.yaml --precompute true --json
```

## Minimum validation
```bash
pytest -q tests/test_execution_replay.py tests/test_signal_replay_core.py tests/test_signal_replay_golden_parity.py tests/backtest_v2
```

## Guardrails
- Do not mix benchmark windows between baseline and candidate.
- Do not hide cache mode when reporting runtime numbers.
- Do not couple more workers than storage/network can sustain.
- Do not break minute replay canon for local speed gains.
- Always include cold and warm measurements when cache exists.

## Output format
```markdown
## Performance scope
- Goal:
- Window and dataset:
- Cache mode:
- Parallel topology:

## Runtime results
- Baseline (cold/warm):
- Candidate (cold/warm):
- Delta:

## Correctness checks
- Replay invariants:
- Regression tests:

## Recommendation
- Keep / rollback / iterate:
- Next bottleneck:
```
