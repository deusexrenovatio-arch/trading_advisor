# Glossary

## Core data objects
- Instrument: a traded security (stock, future, bond, ETF) identified by `secid`.
- ContractSpec: futures contract specification (expiry, lot size, multiplier, tick size).
- Stock: an equity instrument on MOEX (TQBR board by default).
- Futures contract: a derivatives instrument with a defined expiry and multiplier.
- Pair (stock-future pair): a linked stock and its corresponding futures contract.
- PairMapping: stored mapping between a stock and a future, including expiry.

## Signals and decisions
- Signal: a strategy output with direction, score, reasons, and metrics.
- SignalDecision: normalized decision output from a strategy module
  (`action`, `direction`, `score`, `reasons`, `metrics`).
- Strategy signal: normalized signal payload passed into the aggregator.
- Strategy: a family of logic (fundamental, speculative, arbitrage).
- Portfolio proposal: a set of target allocations for instruments.
- Allocation: per-instrument intent (`side`, `target_weight`, `quantity`).
- Risk check: a single deterministic risk validation with pass/fail.
- Risk gate: the set of checks that determine allow/reduce/block.
- News filter: event-driven gate that can reduce or block actions.
- Decision log: canonical immutable record of each decision.
- Decision view: UI projection derived from the decision log.

## Data lineage
- Input snapshot: immutable snapshot reference used for reproducibility.
- Feature set: versioned set of computed features with snapshot references.
- Backtest metrics: performance summary (cagr, sharpe, drawdown, turnover).
- Cost model: fee/slippage/tax estimates used for break-even logic.
- Risk profile: user-specified limits and constraints for risk gating.

## Trading math
- Spread: price difference between legs of a pair.
- SpreadPct: spread normalized by spot mid price.
- Z-score: standardized spread score used for entry/exit thresholds.
- Carry / implied rate: annualized yield implied by spot vs future pricing.
- DTE: days to expiry for the futures contract.
- Tau: year fraction between now and expiry (day-count convention).
- Hedge ratio: weighting between legs in spread arbitrage.
- RTC (round-trip cost): estimated entry + exit cost in spread units.
- Floor rate: expected annualized carry return if held to expiry.
- TP/SL: take-profit and stop-loss thresholds for alpha exits.
- MFE/MAE: max favorable/adverse excursion over a horizon.
- Days-to-exit: estimated trading days required to unwind a position.
- Liquidity score: a relative measure used to penalize illiquid instruments.

## Operations
- Rebalance cadence: frequency of portfolio adjustments (weekly for v1).
- Execution log: recorded manual execution or broker action.
- Top pairs: derived ranking output (CSV) used by the UI and pipeline.
