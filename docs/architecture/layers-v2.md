# Layers v2

## Purpose
This document defines bounded layers for the modular monolith v2 and maps ownership.

## Layer map

### 1) Instrument Analytics Layer
- Scope: market ingestion, snapshots, feature engineering for instruments and pairs.
- Inputs: MOEX/CBR/history adapters, cached snapshots.
- Outputs: `MarketSnapshot`, `PairSnapshot`, `FeatureSet`.
- Owner: backend analytics.

### 2) Signal & Decision Layer
- Scope: normalized strategy signals, gate evaluation, lifecycle state, decision projection.
- Inputs: analytics features, risk profile, news severity, pretrade checks.
- Outputs: `SignalRef`, `GateResult`, `DecisionRecord`, `DecisionView`.
- Owner: backend strategy.

### 3) Strategy Research Layer
- Scope: backtest v2, HPO, forward runtime, experiment metadata and promotion gates.
- Inputs: strategy requests, snapshot universe, objective config.
- Outputs: `ResearchExperiment`, `BacktestRun`, `HpoRun`, run status.
- Owner: quant/research.

### 4) News Intelligence Layer
- Scope: normalized event feed, severity mapping, links to domain entities.
- Inputs: news providers, decision logs.
- Outputs: `NewsEvent`, `NewsEntityLink`, `news/feed` projections.
- Owner: data + risk.

### 5) Portfolio & Rebalance Layer
- Scope: target allocation proposals and rebalance plans with turnover/risk checks.
- Inputs: active signal lifecycle, current portfolio state, risk policy.
- Outputs: `RebalancePlan`, portfolio preview/commit artifacts.
- Owner: portfolio engineering.

### 6) Execution & Audit Layer
- Scope: action capture (`ack|enter|exit|hold_open`), order linking, audit trail.
- Inputs: operator actions (UI/bot/system), signal references.
- Outputs: `ExecutionEvent`, audit runbooks, incident traces.
- Owner: execution platform.

## Boundary rules
- UI does not compute business lifecycle states.
- Research engines do not bypass RiskGate semantics.
- Performance optimizations must preserve minute replay invariants.
- Cross-layer contracts are versioned and backward compatible by default.

## API boundary summary
- `/api/v2/signals/*`: Signal & Decision + Execution.
- `/api/v2/decisions/*`: Decision projection.
- `/api/v2/news/*`: News Intelligence.
- `/api/v2/research/*`: Strategy Research.
- `/api/v2/portfolio/*`: Portfolio & Rebalance.
