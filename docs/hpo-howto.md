# HPO How-To (Backtest v2 Black Box)

This guide shows how to run HPO locally using the `moex_carry.hpo` module
and the async API endpoints (`/api/hpo/run`, `/api/hpo/status`).

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

## 1.1) (Optional) Run via API (async)
Start a run:
```
POST /api/hpo/run
{
  "base": { ...BacktestRequest... },
  "search_space": { ... },
  "cv": { ... },
  "optimization": { "max_trials": 10, "metric": "excess_ann", "mode": "max" }
}
```
Poll status:
```
GET /api/hpo/status?run_id=...
```
When status becomes `completed`, the response includes `result.leaderboard`.

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

Default production mode is portfolio-first:
- `scope=PORTFOLIO`
- `portfolio_metric=utility`
- fold evaluation uses minute portfolio path (`compute_minute_portfolio_window_metrics`)
  with minute replay execution semantics.

Pair-mean mode is kept only for diagnostics/benchmarks (`scope=PAIR_MEAN`).

### 3.1 Pair-mean objective (debug mode)
Objective in pair-mean mode:

```
J = ExcessAnn
    - lambda_dd * max(0, MaxDD - DDmax)
    - lambda_to * max(0, AvgTurnover - TOmax)
```

If constraints are violated, `J = -INF`. Note: `MaxDD` in metrics is negative,
so the HPO objective uses its absolute value; set `DDmax` as a positive fraction.

You can switch the metric and mode:
- `metric`: `excess_ann`, `cagr`, `ir`, `vol_ann`, `max_dd`, `avg_turnover`,
  `win_rate`, `profit_factor`, `avg_hold_days`, `share_alpha_exits`,
  `r_d`, `b_d`, `ex_d`, `sharpe`.
- `mode`: `max` or `min`.

### 3.2 Portfolio utility objective (default)

```
Utility = PortfolioExcessAnn
          - lambda_dd * max(0, PortfolioMaxDD - dd_soft_limit)
          - lambda_idle * PortfolioIdleRatio
          - lambda_forced * PortfolioForcedExitRate
          - lambda_unfilled * PortfolioUnfilledEntryRate
          - lambda_turnover * PortfolioTurnover
```

Hard constraints invalidate objective when violated:
- `PortfolioMaxDD > hard_max_dd`
- `PortfolioIdleRatio > hard_max_idle_ratio`
- `PortfolioForcedExitRate > hard_max_forced_exit_rate`
- `PortfolioUnfilledEntryRate > hard_max_unfilled_entry_rate`

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
    scope="PORTFOLIO",
    portfolio_metric="utility",
    mode="max",
    lambda_dd=2.0,
    dd_soft_limit=0.2,
    lambda_idle=0.6,
    lambda_forced=0.4,
    lambda_unfilled=0.3,
    lambda_turnover=0.1,
    hard_max_dd=0.30,
    hard_max_idle_ratio=0.75,
    hard_max_forced_exit_rate=0.40,
    hard_max_unfilled_entry_rate=0.50,
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
- Portfolio-scope trials include:
  - `evaluation_scope` (`PORTFOLIO`),
  - `objective_breakdown` (base metric, penalties, hard-gate outcome).

## Notes
- `CONTINUOUS` runs a single backtest per fold and slices metrics by val/test windows.
- `WARMUP_THEN_FLAT` runs warmup to `val_start` and then evaluates from a reset
  equity baseline (extra backtest runs per fold).
- Use `precompute=True` to enable Backtest v2 precompute/fast alpha paths.
- If `search_space` contains invalid keys, validation errors will surface from
  `BacktestRequest` during trial construction.
- If the requested history window is short, the async runtime auto-scales fold lengths
  (fallback split) and sets embargo to 0; `folds_meta.fallback=true` will be returned
  in the status/result payload.
- `rates.use_trading_days=true` switches annualization to 252 trading days
  (affects ExcessAnn, Vol_ann, IR, Sharpe).

## 5) Morning-plan intraday HPO (causal walk-forward)
Use `scripts/run_morning_plan_walk_forward.py` with TPE search to avoid brute-force grids.

Strategy objective for this stream:
- potential setup target from `0.5%` and higher (`setups.min_target_return_pct`),
- several entries per week (default search target band `2..12`),
- mandatory intraday exit (`EOD` / before evening clearing).

Example command:

```bash
PYTHONPATH=src python scripts/run_morning_plan_walk_forward.py \
  --search-algorithm TPE \
  --search-space-profile intraday_goal_v1 \
  --hpo-trials 24 \
  --hpo-startup-trials 8 \
  --goal-min-target-return-pct 0.5 \
  --goal-min-trades-per-week 2 \
  --goal-max-trades-per-week 12 \
  --goal-trade-freq-penalty 3.0 \
  --tuning-profile cost_aware_v2 \
  --cost-model-profile fixed_v1 \
  --offline-only \
  --start-date 2026-01-05 \
  --end-date 2026-03-02 \
  --decision-time 12:00 \
  --train-days 20 \
  --test-days 7 \
  --step-days 7 \
  --instrument BRH6 --instrument NGH6 ... \
  --out-json data/output/research/morning_offline_wf_tpe_intraday_goal_v1.json
```

## Spread tolerance profile (ready-to-run)
Use `configs/hpo_spread_tolerance_portfolio.yaml` to tune spread entry bands in
minute replay with portfolio utility penalties.

This profile searches:
- `strategy.entry_spread_tolerance_pct`
- `strategy.entry_stock_tolerance_pct`
- `strategy.entry_future_tolerance_pct`
- `strategy.execution_max_wait_minutes`
- `strategy.signal_cutoff_before_day_end_minutes`

Portfolio utility already penalizes low reuse / high idle behavior:
- `PortfolioIdleRatio`
- `PortfolioUnfilledEntryRate`
- `PortfolioTurnover`
- `PortfolioForcedExitRate`
