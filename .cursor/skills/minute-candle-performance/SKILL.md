---
name: minute-candle-performance
description: "Performance engineering workflow for high-volume minute-candle workloads in this repository: stack policy, replay acceleration, cache design, chunking, and deterministic parallelization. Use when requests mention optimization, runtime scaling, bottlenecks, minute replay, heavy backtest batches, or parallel execution. Use during performance rechecks and before push for minute/high-load changes."
---

# Minute Candle Performance

## Overview
Use this skill to make minute-candle workloads fast and deterministic: profile first, optimize inside boundaries, and keep parity with fallback paths.

## Skill dependencies and lifecycle gates
- Start phase: run `parallel-worktree-flow` first if this is a new implementation stream.
- Architecture phase: run `architecture-review` first when boundaries/dependencies or ownership change.
- Research quality phase: run `ml-backtest-hpo-lab` for OOS and stress validation after performance changes.
- Recheck/pre-push phase: rerun parity/performance checks and required checks from `docs/DEV_WORKFLOW.md`.


## Repository governance baseline (mandatory)
- Follow `docs/workflows/skill-governance-sync.md` for mandatory repository gates (worktree guard, lean loop, plans/memory/handoff, pre-push blockers, repeated-issue escalation).
- Keep this skill focused on domain workflow; do not duplicate repository governance details here.

## Coordination with architecture-review
- Apply in order:
  1. `architecture-review`: validate module boundaries and dependency direction.
  2. `minute-candle-performance`: optimize kernels/orchestration inside approved boundaries.
- If architecture and performance goals conflict, keep boundary correctness first.

## Repository anchors
- `scripts/intraday_minute_sweep.py` for scenario replay and cache preparation.
- `scripts/prewarm_intraday_cache.py` to prime preload cache without full replay.
- `scripts/period_pnl_parallel_runner.py` for sharded parallel runs across scenarios or pairs.
- `src/moex_carry/backtest_v2/runtime.py` for precompute and fill-quality cache logic.
- `src/moex_carry/backtest_v2/batch.py` for vectorized batch scoring.
- `src/moex_carry/analytics/alpha.py` for optional numba kernels with numpy fallback.
- `docs/architecture/modules/minute-replay-canon-v1.md` for replay invariants.
- `docs/acceptance/minute-first-acceptance-2026-02-12.md` for current performance gates.
- `references/perf-playbook.md` for tuning matrix and reporting checklist.
- `references/stack-architecture.md` for stack selection policy.

## Compute architecture and stack policy
- Layer workloads:
  - I/O and normalization layer.
  - Numeric kernel layer.
  - Orchestration layer.
- Select stack by layer:
  - `pandas` only at ingestion/report boundaries.
  - `numpy` by default for hot paths.
  - `numba` only for profiled numeric hotspots with stable parity.
- Block anti-patterns:
  - Row-wise `DataFrame.apply` in hot paths.
  - Per-row Python loops over candles in inner loops.
  - Repeated `DataFrame <-> ndarray` conversion in compute loops.
- Keep deterministic fallback path for every optimized kernel.

## Workflow
1. Define target before coding:
- Choose profile (cold, warm, throughput, batch completion).
- Freeze dataset window, pair set, and scenario grid for comparison.
- Record hardware profile.

2. Separate I/O and compute:
- Warm cache first to isolate compute bottlenecks.
- Keep `preload_cache_mode` explicit (`readonly`, `readwrite`, `refresh`).
- Tune `minute_chunk_days` for overhead vs memory.

3. Choose stack early:
- Estimate complexity as `days x pairs x scenarios x feature_count`.
- For heavy numeric loops, start with `numpy` (and optional `numba`) instead of row-wise pandas.

4. Choose parallel axis explicitly:
- Shard by pair when pairs are large and scenario count is small.
- Shard by scenario when scenarios are large and pair universe is stable.
- Keep `--jobs` independent from `--pair-workers` and `--preload-workers`.

5. Preserve deterministic outputs:
- Use fixed pair/scenario lists and stable sort keys.
- Emit explicit shard artifacts and merge deterministically.

6. Validate correctness and speed together:
- Run replay invariants and regression tests.
- Report both behavior and runtime deltas.

7. Close review gates:
- Confirm stack policy compliance in `docs/architecture/modules/compute-stack-policy.md`.
- Update acceptance notes with cold/warm timings, cache mode, and hardware profile.

## Core commands
```bash
python scripts/prewarm_intraday_cache.py --config configs/default.yaml --lookback-days 400 --preload-cache-mode readwrite --preload-workers 4 --minute-chunk-days 21
python scripts/period_pnl_parallel_runner.py --config configs/default.yaml --scenario-specs-file data/output/period_scenarios.txt --pairs-file data/output/front_pairs.txt --jobs 4 --pair-workers 1 --preload-workers 4 --minute-chunk-days 21 --preload-cache-mode readonly
python -m moex_carry.cli backtest_v2 --config configs/default.yaml --precompute true --json
```

## Minimum validation
```bash
python scripts/sync_architecture_map.py --check
pytest -q tests/test_execution_replay.py tests/test_signal_replay_core.py tests/test_signal_replay_golden_parity.py tests/backtest_v2
```

## Guardrails
- Do not compare mixed benchmark windows.
- Do not hide cache mode in runtime reports.
- Do not oversubscribe workers beyond storage/network capacity.
- Do not ship speedups without replay parity evidence.
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
## Mandatory pre-push guidance
- Run `python scripts/sync_architecture_map.py --check` when boundaries or integrations are touched.
- Run required checks from `docs/DEV_WORKFLOW.md` for touched areas; treat failures as blockers.
- If contracts/registry/docs changed, update source-of-truth artifacts before push and keep notes in AGENTS or PR summary.
