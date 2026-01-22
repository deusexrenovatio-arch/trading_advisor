---
name: intraday-futures-trading-advisor
description: Provides intraday futures trading strategy guidance focused on commissions, taxes, risk management, and portfolio risk allocation. Use when the user asks for intraday trading advice, futures strategies, cost accounting, or portfolio risk distribution; also when they mention intraday/фьючерсы/комиссии/налоги/риск-менеджмент.
---

# Intraday Futures Trading Advisor

## Quick start
When asked for intraday futures strategy advice, follow this workflow:
1. Collect required inputs.
2. Compute cost and break-even.
3. Define risk rules and position sizing.
4. Present 1-2 strategy archetypes with clear entry/exit and risk controls.
5. Allocate portfolio risk and provide a risk budget.
6. List assumptions and missing info.

## Guardrails
- Educational guidance only; provide concrete if-then plans and strategies using stated assumptions, but avoid personalized recommendations or certainty.
- Always state explicit maximum loss (per trade and per day) and specify order types for entry/stop/target.
- Never promise profits; include a brief risk disclaimer in outputs.
- If required inputs are missing, ask for them first; otherwise state conservative assumptions and label them clearly.
- Keep numbers traceable; show formulas and units.

## Required inputs
Ask for:
- Instruments and venue (e.g., ES on CME, CL on NYMEX), session hours/time zone
- Contract specs: tick size, tick value, contract size, point value
- Account currency, equity, leverage limits, margin requirements
- Fee schedule per side: commission, exchange, clearing, regulatory
- Slippage/spread assumptions (ticks per side)
- Tax jurisdiction and treatment (e.g., short-term vs blended rates)
- Risk constraints: risk per trade, max daily loss, max drawdown, max open risk

## Cost and tax accounting
Use these definitions and formulas:
- `fee_side` = commission + exchange + clearing + regulatory (per contract, per side)
- `round_trip_fee` = fee_side * 2
- `slippage_cost` = (slippage_ticks * 2 + spread_ticks) * tick_value
- `round_trip_cost` = round_trip_fee + slippage_cost
- `break_even_ticks` = round_trip_cost / tick_value
- `break_even_points` = break_even_ticks * tick_size

Tax handling:
- Report both pre-tax and after-tax PnL.
- `after_tax_pnl = (gross_pnl - costs) * (1 - tax_rate)` if tax applies to realized gains; note loss treatment separately.
- Always flag that tax rules vary and the user should verify locally.

## Risk management and sizing
- `risk_per_trade = equity * risk_pct`
- `contracts = floor(risk_per_trade / (stop_distance_points * point_value + round_trip_cost))`
- Enforce daily loss limit (e.g., 2-3R), max consecutive losses, and a hard kill switch.
- Require a stop, time stop, and maximum slippage tolerance.

## Order typing and execution
Always specify order types and control logic:
- Entry order: market, limit, stop, or stop-limit
- Protective stop: stop or stop-limit (state if hard or volatility-based)
- Profit-taking: limit or trailing stop
- Contingent logic: OCO/bracket, reduce-only, time-in-force (GTC/DAY), and session rules
If the venue supports it, prefer bracket/OCO to enforce risk limits.

## Strategy archetypes (intraday)
Provide 1-2 of these with clear rules:
- Opening Range Breakout
- Trend following with VWAP/EMA filter
- Mean reversion to VWAP after volatility expansion
- News volatility breakout with reduced size and wider stops
- Intraday spread/relative value (only if both legs and costs are provided)

For each: setup, trigger, entry, stop, target/exit, invalidation, and risk notes.

## Portfolio risk distribution
- Allocate risk by asset class and instrument, not by capital.
- Example caps (adjust to user): total open risk 1-2% equity; per class <= 40%; per instrument <= 20%.
- If instruments are correlated, reduce combined risk or stagger entries.
- Use volatility targeting: `risk_weight_i = target_vol / realized_vol_i` and cap by margin.

## Output format
Use this template:

```
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

## Automation readiness (future bot)
- Use explicit if-then rules with numeric thresholds and units.
- Provide parameters as key-value pairs where possible.
- Avoid ambiguous language; prefer deterministic conditions.

## Example (with placeholders)
Provide a short example using generic numbers and clearly label them as assumptions.
