# Entities Catalog

## Scope
This catalog lists domain and persistence entities used by the core pipeline.

## Domain entities (`src/moex_carry/domain`)

### `models.py`
- `Instrument`: security metadata (secid, type, currency, board).
- `ContractSpec`: futures contract specs (expiry, lot size, multiplier).
- `PairMapping`: mapping between stock and future legs.
- `Quote`: market quote snapshot (bid/ask/last/volume).
- `DividendEvent`: corporate action with ex-date and amount.
- `KeyRate`: central bank key rate time series.
- `Signal`: strategy signal with score, reasons, and metrics.
- `Trade`: trade lifecycle with entry/exit and pnl.
- `BacktestRun`: backtest metadata and parameters.

### `decision.py`
- `RiskProfile`: risk limits used by `risk_gate`.
- `NewsItem`: normalized news/event input to `news_filter`.
- `DecisionRecord`: paired `decision_log` + `decision_view` payloads.

## Strategy entities (`src/moex_carry/strategy`)
- `SignalDecision`: normalized strategy decision output
  (`action`, `direction`, `score`, `reasons`, `metrics`).
- `StrategySignal`: normalized module signal payload for aggregation.
- `StrategyAllocation`: per-instrument allocation intent.
- `RuleEvaluation`: deterministic rule evaluation with severity.
- `AggregationResult`: aggregated action, allocations, and audit metadata.

## Persistence entities (`src/moex_carry/storage`)

### `models.py`
- `InstrumentModel`
- `ContractSpecModel`
- `PairMappingModel`
- `QuoteModel`
- `DividendEventModel`
- `KeyRateModel`
- `SignalModel`
- `SignalRunModel`
- `SignalHistoryModel`
- `SignalExecutionModel`
- `TradeModel`
- `BacktestRunModel`

These map closely to the domain entities but include database fields such as
primary keys, indexes, and JSON payload columns.
