---
name: intraday-futures-trading-advisor
description: Provides intraday futures strategy guidance focused on commissions, taxes, risk controls, and portfolio risk allocation. Use when requests mention intraday trading, futures strategy, cost accounting, or risk budgeting. Co-use with moex-instruments-costs, risk-profile-gates, and news-geopolitics-filter for deterministic checks; add spread-arbitrage for pair-spread setups.
---

# Intraday Futures Trading Advisor

## Quick start
When asked for intraday futures strategy advice, follow this workflow:
1. Collect required inputs.
2. Compute costs and break-even.
3. Define risk rules and position sizing.
4. Present one or two strategy archetypes with entry/exit and controls.
5. Allocate portfolio risk.
6. List assumptions and missing inputs.

## Skill dependencies and lifecycle gates
- Start phase: if this is part of a new implementation stream, run `parallel-worktree-flow` first.
- Strategy design phase: run `moex-instruments-costs` and `risk-profile-gates` for deterministic validation.
- Event-risk phase: run `news-geopolitics-filter` when macro/news conditions can block or reduce exposure.
- Spread phase: run `spread-arbitrage` for two-leg spread plans.
- Recheck/pre-push phase: rerun deterministic gates above and ensure required checks from `docs/DEV_WORKFLOW.md` pass.

## Guardrails
- Provide educational guidance only; avoid certainty and personalized recommendations.
- Always state explicit maximum loss per trade and per day.
- Always specify order types for entry, stop, and target.
- Never promise profits; include a concise risk disclaimer.
- If required inputs are missing, ask for them or state conservative assumptions.
- Keep formulas and units explicit.

## Required inputs
Ask for:
- Instruments and venue (for example ES on CME, CL on NYMEX), session hours, and time zone.
- Contract specs: tick size, tick value, contract size, point value.
- Account currency, equity, leverage limits, margin requirements.
- Fee schedule per side: commission, exchange, clearing, regulatory.
- Slippage and spread assumptions (ticks per side).
- Tax jurisdiction and treatment.
- Risk constraints: risk per trade, max daily loss, max drawdown, max open risk.

## Cost and tax accounting
Use these definitions:
- `fee_side = commission + exchange + clearing + regulatory`
- `round_trip_fee = fee_side * 2`
- `slippage_cost = (slippage_ticks * 2 + spread_ticks) * tick_value`
- `round_trip_cost = round_trip_fee + slippage_cost`
- `break_even_ticks = round_trip_cost / tick_value`
- `break_even_points = break_even_ticks * tick_size`

Tax handling:
- Report both pre-tax and after-tax PnL.
- `after_tax_pnl = (gross_pnl - costs) * (1 - tax_rate)` when tax applies to realized gains.
- State that tax rules vary and require local verification.

## Risk management and sizing
- `risk_per_trade = equity * risk_pct`
- `contracts = floor(risk_per_trade / (stop_distance_points * point_value + round_trip_cost))`
- Enforce daily loss limit, max consecutive losses, and hard kill switch.
- Require stop, time stop, and max slippage tolerance.

## Order typing and execution
Specify order types and control logic:
- Entry: market, limit, stop, or stop-limit.
- Protective stop: stop or stop-limit (hard or volatility-based).
- Profit taking: limit or trailing stop.
- Contingent logic: OCO/bracket, reduce-only, TIF, and session rules.

## Strategy archetypes (intraday)
Provide one or two with clear rules:
- Opening range breakout.
- Trend following with VWAP or EMA filter.
- Mean reversion to VWAP after volatility expansion.
- News-volatility breakout with reduced size.
- Intraday spread or relative-value (only if both legs and costs are provided).

For each archetype provide setup, trigger, entry, stop, target/exit, invalidation, and risk notes.

## Portfolio risk distribution
- Allocate by risk, not by nominal capital.
- Example caps: total open risk 1-2% equity; per class <= 40%; per instrument <= 20%.
- Reduce combined risk for correlated instruments.
- Use volatility targeting: `risk_weight_i = target_vol / realized_vol_i`, capped by margin.

## Output format
Use this template:

```markdown
## Strategy blueprint
- Objective/timeframe:
- Markets/instruments:
- Setup and triggers:
- Entry/exit rules:
- Order types (entry/stop/target, TIF, OCO/bracket):
- Risk and position sizing:
- Trade management:

## Cost and tax sheet
- Fees (per side):
- Slippage/spread assumptions:
- Round-trip cost and break-even:

## Portfolio risk allocation
- Risk budget by class/instrument:
- Correlation adjustments:
- Max open risk:

## Assumptions and missing inputs
- ...
```

## Automation readiness
- Express conditions as explicit if-then rules with numeric thresholds and units.
- Provide parameters as key-value pairs where possible.
- Avoid ambiguous language.
