# Entities v2

## Canonical identity model

### Issuer
- `issuer_id` (string, stable)
- `sector` (string)
- `country` (string)

### Asset
- `asset_id` (string, stable)
- `ticker` (string)
- `isin` (string, optional)
- `issuer_id` (string, FK -> Issuer)
- `asset_class` (`stock|future|bond|etf|other`)

### Instrument
- `instrument_id` (string, stable)
- `secid` (string, venue identifier)
- `venue` (string)
- `type` (`stock|future|bond|etf`)
- `underlying_asset_id` (string, FK -> Asset, optional)
- `expiry` (date, optional)

### Pair
- `pair_id` (string, stable)
- `stock_instrument_id` (FK -> Instrument)
- `future_instrument_id` (FK -> Instrument)
- `strategy_universe_tag` (string)

## Market and feature entities

### MarketSnapshot
- `snapshot_id`
- `instrument_id`
- `ts`
- `source`
- `hash`

### PairSnapshot
- `pair_snapshot_id`
- `pair_id`
- `spread_metrics` (object)
- `floor_metrics` (object)
- `alpha_metrics` (object)
- `liquidity_metrics` (object)
- `news_metrics` (object)

### FeatureSet
- `feature_set_id`
- `entity_type` (`instrument|pair|portfolio`)
- `entity_id`
- `feature_version`
- `features` (map)

## Signal and decision entities

### EntityRef
- `entity_type` (`instrument|pair|portfolio`)
- `entity_id`
- `asset_id` (optional)
- `ticker` (optional)

### StrategySignal
- `signal_id`
- `strategy_id`
- `entity_ref`
- `action` (`enter|exit|hold`)
- `confidence`
- `metadata`

### GateResult
- `gate_result_id`
- `signal_id`
- `gate_type` (`risk|news|pretrade|score_gate`)
- `status` (`pass|warn|block`)
- `reasons` (array)

### DecisionRecord
- `decision_id`
- `signal_ids` (array)
- `action`
- `risk_state`
- `links`

### DecisionAction
- `action_id`
- `decision_id`
- `source` (`ui|telegram|system`)
- `actor`
- `note`
- `created_at`

### ExecutionEvent
- `execution_event_id`
- `signal_id` or `decision_id`
- `action` (`ack|enter|exit|hold_open`)
- `order_id` (optional)
- `metadata`

## Research entities

### ResearchExperiment
- `experiment_id`
- `hypothesis`
- `window`
- `mode`
- `constraints`

### BacktestRun
- `run_id`
- `request_hash`
- `summary_metrics`
- `artifacts`

### HpoRun
- `hpo_run_id`
- `folds_meta`
- `objective`
- `status`
- `result`

## Portfolio entities

### PortfolioState
- `portfolio_state_id`
- `as_of`
- `positions`
- `cash`
- `equity`

### RebalancePlan
- `rebalance_plan_id`
- `positions`
- `risk_checks`
- `turnover_checks`
- `generated_at`
