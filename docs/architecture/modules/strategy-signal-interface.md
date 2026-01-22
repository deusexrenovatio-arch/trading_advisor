# Strategy Signal Interface

## Scope
Defines the normalized signal contract used between strategy modules and the
overall strategy aggregator. This keeps module development independent.

## Why this exists
- Decouple module implementations from the aggregator.
- Avoid direct dependencies between modules.
- Allow stub integration while modules evolve.

## Canonical payload
`StrategySignal` represents one module intent for the current rebalance cycle.

Required fields:
- `strategy_id`: stable identifier for the module (e.g. `spread_arbitrage_v1`).
- `strategy_type`: `fundamental` | `speculative` | `arbitrage`.
- `cadence`: `intraday` | `daily` | `weekly` (free-form string is allowed).
- `horizon`: time horizon string (e.g. `intraday`, `short`, `mid`, `long`).
- `action`: `enter` | `exit` | `hold`.
- `confidence`: float 0..1.

Optional fields:
- `expected_return`: float (annualized or period return, documented by module).
- `risk_estimate`: float (volatility, VaR, or other module-defined measure).
- `liquidity_score`: float 0..1.
- `instruments`: list of instrument `secid`s involved.
- `intent_allocations`: list of target allocations (see below).
- `rules_evaluated`: list of rule evaluations (see below).
- `warnings`: list of strings.
- `metadata`: free-form dictionary for module-specific fields.

### Allocation payload
- `instrument`: `secid`
- `side`: `long` | `short` | `flat`
- `target_weight`: optional float
- `quantity`: optional float

### Rule evaluation payload
- `rule_id`: stable rule identifier
- `result`: boolean
- `severity`: `info` | `warn` | `block`
- `description`: optional string

## Integration pattern (non-blocking)
- The aggregator accepts zero or more `StrategySignal` entries.
- If a module is not ready, it supplies no signals and the aggregator proceeds.
- The adapter stub lives in `src/moex_carry/strategy/spread_adapter.py` and
  can be replaced later without touching the aggregator.

## Example JSON
```json
{
  "strategy_id": "spread_arbitrage_v1",
  "strategy_type": "arbitrage",
  "cadence": "intraday",
  "horizon": "short",
  "action": "enter",
  "confidence": 0.72,
  "expected_return": 0.08,
  "risk_estimate": 0.12,
  "liquidity_score": 0.9,
  "instruments": ["SBER", "SRH5"],
  "intent_allocations": [
    { "instrument": "SBER", "side": "long", "target_weight": 0.5 },
    { "instrument": "SRH5", "side": "short", "target_weight": 0.5 }
  ],
  "rules_evaluated": [
    { "rule_id": "z_entry", "result": true, "severity": "info" }
  ],
  "warnings": [],
  "metadata": { "hedge_ratio": 0.8, "entry_zscore": 2.1 }
}
```
