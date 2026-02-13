# Minute Candle Performance Playbook

## 1) Benchmark profiles
- `cold`: empty cache, first load path, include fetch + preprocess.
- `warm`: cache populated, steady-state runtime.
- `batch`: many scenarios or pairs across shards.

Always report all profiles that apply.
Architecture and stack policy for implementation choices lives in `stack-architecture.md`.

## 2) Key knobs and effects
- `--jobs`:
  - Process-level shards in `period_pnl_parallel_runner.py`.
  - Increase until CPU saturates or I/O contention dominates.
- `--pair-workers`:
  - In-scenario pair parallelism.
  - Useful when per-pair compute is heavy and cache is warm.
- `--preload-workers`:
  - Parallel cache miss loading.
  - Useful for cold or refresh runs.
- `--minute-chunk-days`:
  - Fetch chunk size for minute candles.
  - Too small increases overhead; too large increases memory and long-request risk.
- `--preload-cache-mode`:
  - `readonly`: deterministic warm-run timing, fails on misses.
  - `readwrite`: default for incremental cache growth.
  - `refresh`: force full rebuild for cache invalidation events.

## 3) Recommended tuning order
1. Fix benchmark dataset and scenario set.
2. Warm cache once with `prewarm_intraday_cache.py`.
3. Tune `minute_chunk_days` on 1-2 representative pairs.
4. Tune `preload-workers` for cold path.
5. Tune `jobs` and `pair-workers` for warm batch path.
6. Re-run correctness and parity tests.

## 4) Example runs
```bash
python scripts/prewarm_intraday_cache.py --config configs/default.yaml --pairs-file data/output/front_pairs.txt --lookback-days 400 --preload-cache-mode readwrite --preload-workers 4 --minute-chunk-days 21

python scripts/period_pnl_parallel_runner.py --config configs/default.yaml --scenario-specs-file data/output/period_scenarios.txt --pairs-file data/output/front_pairs.txt --jobs 4 --shard-axis auto --pair-workers 1 --preload-workers 4 --minute-chunk-days 21 --preload-cache-mode readonly
```

## 5) Performance gates to track
- Warm minute runtime should stay close to daily baseline on same dataset.
- Cold minute runtime should stay within agreed SLO for reference pair count.
- Throughput should scale with shards until saturation, then flatten predictably.

Reference baseline and gate examples:
- `docs/acceptance/minute-first-acceptance-2026-02-12.md`

## 6) Correctness gates after optimization
- `tests/test_execution_replay.py`
- `tests/test_signal_replay_core.py`
- `tests/test_signal_replay_golden_parity.py`
- `tests/backtest_v2`

## 7) Common anti-patterns
- Oversubscribing workers on network-bound stages.
- Comparing warm candidate vs cold baseline.
- Changing cache mode between compared runs without disclosure.
- Optimizing compute path while regressing replay causality/timestamp rules.
