# HPO How-To (Backtest v2 Black Box)

This guide shows how to run HPO locally using the `moex_carry.hpo` module.
The HPO runner is **not** wired to API/CLI yet (the UI calls `/api/hpo/run`, which returns a stub),
so use Python directly for real optimization runs.

## Prerequisites
- Historical candles under `data/history/candles/` (stocks + futures).
- Reference data under `data/raw/` (`shares.csv`, `futures.csv`, `key_rates.csv`).
- Dependencies installed (`pip install -e .[dev]`).

## 1) Prepare a base BacktestRequest
Create a YAML file with a minimal Backtest v2 request:

```yaml
# configs/hpo_request.yaml
test:
  start_date: 2020-01-01
  end_date: 2024-12-31
universe:
  include_stocks: [SBER]
  include_futures: [SRH6]
  max_pairs: 1
strategy:
  z_window: 60
  TP_pct: 0.01
  SL_pct: 0.01
portfolio:
  account_equity: 1000000
allocation:
  max_turnover_pct: 0.2
rebalance:
  cadence: weekly
```

You can reuse the same schema as `backtest_v2` requests.

## 2) Define search space and folds
Search space keys use dotted paths (e.g., `strategy.z_window`).

```python
from pathlib import Path

from moex_carry.backtest_v2.runtime import build_universe_from_request
from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.data.history_store import HistoryDataStore
from moex_carry.hpo import build_walk_forward_folds

data_dir = Path("data")
request = BacktestRequest.model_validate({
    "test": {"start_date": "2020-01-01", "end_date": "2024-12-31"},
    "universe": {"include_stocks": ["SBER"], "include_futures": ["SRH6"], "max_pairs": 1},
})

universe = build_universe_from_request(request, data_dir)
store = HistoryDataStore(
    data_dir,
    universe,
    start_date=request.test.start_date,
    end_date=request.test.end_date,
)
dates = store.get_calendar(request.test.start_date, request.test.end_date)

folds = build_walk_forward_folds(
    dates,
    train_days=252,
    val_days=63,
    test_days=63,
    step_days=63,
    embargo_days=5,
)
```

## 3) Configure objective and run HPO
Objective is:

```
J = ExcessAnn
    - lambda_dd * max(0, MaxDD - DDmax)
    - lambda_to * max(0, AvgTurnover - TOmax)
```

If constraints are violated, `J = -INF`. Note: `MaxDD` in metrics is negative,
so the HPO objective uses its absolute value; set `DDmax` as a positive fraction.

```python
from moex_carry.hpo import ObjectiveConfig, run_hpo

search_space = {
    "strategy.z_window": {"type": "int", "min": 20, "max": 120, "step": 10},
    "strategy.TP_pct": {"type": "float", "min": 0.005, "max": 0.03, "step": 0.005},
    "strategy.SL_pct": {"type": "float", "min": 0.005, "max": 0.03, "step": 0.005},
    "allocation.max_turnover_pct": {"type": "float", "min": 0.1, "max": 0.4},
    "rebalance.cadence": ["weekly", "daily"],
}

objective = ObjectiveConfig(
    lambda_dd=1.0,
    dd_max=0.2,
    lambda_to=0.5,
    to_max=0.3,
)

result = run_hpo(
    base_request=request,
    search_space=search_space,
    folds=folds,
    data_dir=data_dir,
    objective=objective,
    aggregation="median",          # median | p25 | mean
    algorithm="RANDOM",            # RANDOM | TPE
    max_trials=30,
    random_seed=42,
    evaluation_mode="CONTINUOUS",  # CONTINUOUS | WARMUP_THEN_FLAT
    precompute=True,               # use Backtest v2 precompute when possible
)

best = result.best_trial
print(best.objective, best.params)
```

## 4) Interpret results
- `result.leaderboard()` returns trials sorted by objective.
- `result.best_config` is the top parameter dict.
- Each trial contains per-fold objectives and metrics.

## Notes
- `CONTINUOUS` runs a single backtest per fold and slices metrics by val/test windows.
- `WARMUP_THEN_FLAT` runs warmup to `val_start` and then evaluates from a reset
  equity baseline (extra backtest runs per fold).
- Use `precompute=True` to enable Backtest v2 precompute/fast alpha paths.
- If `search_space` contains invalid keys, validation errors will surface from
  `BacktestRequest` during trial construction.
