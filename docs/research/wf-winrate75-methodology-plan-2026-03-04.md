# WF Winrate>75 Methodology Plan (2026-03-04)

## Context
- Target KPI: `winrate_net > 0.75` and trade frequency around `2 trades/week` with `net_ticks_sum > 0`.
- Current blocker: simple precision filtering improves winrate but collapses frequency; recall-heavy configs keep frequency but stay far below target winrate.

## Empirical Baseline Facts
- Baseline integrity issues are real:
  - `setup_id` duplicates: `154 rows`, `109 unique setup_id`, `14 setup_id with >1 filled`.
  - slots in baseline log: only `10:30` and `12:00`; `14:00` absent.
- Historical scan across local reports (`58` parsed `wf_goal*.json`):
  - no run with `winrate>=0.75` and `trades/week>=2.0`.
  - no run even with `winrate>=0.70` and `trades/week>=1.5`.
- On high-recall reports (`v6_negpen6_seed105`, `v6_seed110_neg0`), simple filter axes
  (`min_risk_ticks`, `min_target_return_pct`, `side`, `time`, `setup_kind`, `stop_model`)
  produced `0` feasible candidates for:
  - `winrate>=0.75`
  - `trades/week>=2.0`
  - `net_ticks_sum>0`

## Methodologies To Adopt
- Constrained objective surface (multi-constraint optimization):
  - hard constraints: `winrate>=0.75`, `trades/week>=2.0`, `net>0`, concentration cap.
  - optimize only inside feasible region.
- Data-snooping control in model/rule selection:
  - White Reality Check, Hansen SPA, Model Confidence Set.
- Regime-conditional validation:
  - monthly blocks + volatility regime blocks + event windows.
- Liquidity-aware evaluation:
  - use impact/fill-quality metrics, not only order-book depth snapshots.
- Event-risk point-in-time gating:
  - build event features from official release schedules with as-of semantics.

## New Data To Add (Priority)
- Market microstructure / execution quality:
  - CME Datamine API/FAQ datasets for depth/trade/impact features.
  - MOEX order flow / book-derived features where available.
- Macro event schedules (point-in-time):
  - BLS release schedule, FRED releases metadata.
- Regime features:
  - ATR percentile, trend/range tags, volatility shock tags.
- Portfolio concentration and cluster risk features:
  - top1 net share, HHI, cluster exposure trajectory.

## Hypothesis Families (Beyond Current Filters)
- H-A Recall expansion:
  - add setup families (ORB, VWAP mean-reversion, volatility-compression breakout).
- H-B Two-stage policy:
  - stage 1: high-recall candidate generator.
  - stage 2: precision model/gate constrained by frequency floor.
- H-C Exit redesign for hit-rate:
  - TP1 partial + time-stop + trailing remainder by regime.
- H-D Concentration/risk routing:
  - per-instrument and per-cluster caps before execution.
- H-E Event/liquidity hard gates:
  - no-entry windows around high-impact releases and thin-liquidity conditions.

## Test Protocol (Hypothesis Checks)
- Validation framework:
  - purged + embargo walk-forward.
  - nested WF for hyperparameter/model threshold tuning.
  - stress costs: `x1.5` and `x2.0`.
- Mandatory reports per hypothesis:
  - `winrate_net`, `trades/week`, `net_ticks_sum`, `expectancy`.
  - concentration: `top1_share`, `HHI`.
  - robustness slices: by month, slot, instrument cluster, regime.
- Go/No-Go:
  - Stage-go: `winrate>=0.70`, `trades/week>=1.5`, `net>0`, `top1_share<=0.50`.
  - Final-go: `winrate>=0.75`, `trades/week>=2.0`, `net>0` at `cost x1.5`, `top1_share<=0.35`.

## Iteration Log (H18-H23)
- Artifact: `artifacts/research/wf_goal_v6_h18_h23_iteration_summary_20260304.json`.
- H18 (`recall families + constrained`):
  - `filled=815`, `win=0.5497`, `tpw=15.545`, `net=111292`, `top1_share=0.664`.
  - failed: `hard_min_win_rate_net`, `hard_max_concentration_top_share`.
- H19 (`+ time_stop + lower RR space`):
  - `filled=753`, `win=0.4993`, `tpw=14.362`, `net=38567.5`, `top1_share=0.621`.
  - failed: `hard_min_win_rate_net`, `hard_max_concentration_top_share`.
- H20 (`ORB only + SELL precision`):
  - `filled=53`, `win=0.6226`, `tpw=1.011`, `net=2207.5`, `top1_share=0.427`.
  - failed: `hard_min_win_rate_net`, `hard_min_trades_per_week`.
- H21 (`ORB only, both sides`):
  - `filled=205`, `win=0.5805`, `tpw=3.910`, `net=26183.5`, `top1_share=0.706`.
  - failed: `hard_min_win_rate_net`, `hard_max_concentration_top_share`.
- H22 (`ORB+SELL, 3 slots`):
  - `filled=57`, `win=0.5965`, `tpw=1.087`, `net=1556`, `top1_share=0.400`.
  - failed: `hard_min_win_rate_net`, `hard_min_trades_per_week`.
- H23 (`ORB+SELL + probability gate`):
  - `filled=0`, `win=0.0`, `tpw=0.0`, `net=0`.
  - failed by collapse of coverage (context sparsity).
- H24 (`ORB+EMA+VWAP recall space`):
  - `filled=503`, `win=0.5408`, `tpw=9.594`, `net=9783.5`, `top1_share=0.272`.
  - failed: `hard_min_win_rate_net`.
- H25/H26/H26b/H26c (`VWAP-only probes with precision and forced overrides`):
  - all runs produced `0 setups` / `0 filled` in WF.
  - implication: current `VWAP_PULLBACK_LIMIT` implementation has no effective coverage in this dataset and should be treated as non-viable in current form.

### Operational conclusion from H18-H23
- In current engine geometry, feasible frontier is around:
  - `win ~0.58-0.62` for `tpw ~1.0-4.0`.
- Adding `time_stop` and `VWAP` did not move the frontier upward; `VWAP` currently contributes zero coverage.
- No tested configuration reached the hard target pair:
  - `win >= 0.75` and `tpw >= 1.8-2.0`.
- Next phase must be structural (not filter-only):
  - add new recall families (`VWAP_MR`, `volatility-compression breakout`) with regime routing.
  - move to two-stage policy with calibrated meta-model on expanded candidates.
  - add portfolio concentration hard caps at execution selection step (not only objective penalty).

## First Experiment Queue
- Q1 (P0 data integrity):
  - enforce `setup_uid` uniqueness and `1 setup -> max 1 filled`.
  - dual reporting `raw` + `dedup`.
- Q2 (P0 slot integrity):
  - diagnose missing `14:00` pipeline path and restore/retire slot explicitly.
- Q3 (P1 recall layer):
  - add one new setup family (ORB baseline variant) and measure frequency uplift.
- Q4 (P1 precision layer):
  - fit calibrated precision gate on expanded candidate pool.
- Q5 (P1 exits + concentration):
  - add TP1/time-stop/trailing and concentration caps; rerun full protocol.

## Primary References
- White Reality Check: https://www.econometricsociety.org/publications/econometrica/2000/09/01/reality-check-data-snooping
- Hansen SPA: https://www.jstor.org/stable/27638834
- Model Confidence Set: https://pure.au.dk/portal/en/publications/the-model-confidence-set
- Intraday futures forecasting benchmark context: https://arxiv.org/abs/2505.21278
- Liquidity metrics beyond depth: https://www.cmegroup.com/news/2025/reassessing-liquidity-beyond-order-book-depth.html
- CME Datamine data access: https://www.cmegroup.com/market-data/datamine-faq.html
- CME Datamine API: https://www.cmegroup.com/market-data/datamine-api.html
- FRED releases API: https://fred.stlouisfed.org/docs/api/fred/releases_dates.html
- BLS release schedule: https://www.bls.gov/schedule/news_release/
