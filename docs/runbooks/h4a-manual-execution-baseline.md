# H4A Manual Execution Baseline

## Scope
Operator contract for the current morning-plan intraday futures execution baseline.

## Baseline Status
- Current runtime baseline: `H4A_CAP_OFF`.
- Practical meaning: this is a live operator execution contract, not only "profit-cap off".
- `O1` remains the reference baseline for lineage and comparison, but the active runtime baseline is `H4A_CAP_OFF`.
- If an operator does not follow the rules below, the trade must be treated as a manual override, not as a true `H4A` execution.

## Fixed Baseline Rules

| Rule | Value | Required operator behavior |
| --- | --- | --- |
| Entry improvement | `1` tick | For LIMIT entry, place the order one tick better than the corridor edge used by the signal. |
| LIMIT fallback | `10` minutes, `1` adverse tick target | If LIMIT is still not filled after `10` minutes, replace it with a marketable order. Do not leave the original LIMIT resting and still call the trade `H4A`. |
| Stop widening | `sl_rr=2.5` | After actual fill, recompute the effective protective stop from the realized fill price, not from the original planned entry only. |
| TP rescaling | `tp_rr=0.6` | After actual fill, recompute the effective TP from the realized fill price and widened risk. |
| Profit cap | `max_profit_rr=0.0` | Do not clip profit with the old `0.3R` RR cap. |
| Break-even arming | `break_even_rr=0.1`, `buffer=2` ticks | Once price moves `0.1R` in favor, move stop to `fill + 2 ticks` for BUY or `fill - 2 ticks` for SELL. |
| Trailing | `trail_activation_rr=0.1`, `offset=2` ticks | After `0.1R` favorable move, trail the active stop `2` ticks behind the best favorable price. |
| Time stop | `180` minutes from fill | Close the position no later than `180` minutes after actual fill if neither TP nor stop has closed it earlier. |
| Position sizing | `20_000 RUB` per trade, risk-only cap | Before sending the order, estimate `risk_money_per_lot = (effective stop distance + modeled round-trip cost) * tick_value` and set `qty = max(1, floor(20_000 / risk_money_per_lot))`. If one contract alone is above `20_000 RUB`, keep `1` lot and log the granularity exception. |

## Fee Model
- Broker fee: every executed order costs `0.45 RUB` per contract.
- Additional broker fee: none.
- Exchange fee: applied only to market or taker execution; passive limit or maker execution pays `0`.
- For H4A this means:
  - LIMIT entry filled passively: broker fee only.
  - LIMIT fallback to market: broker fee plus exchange taker fee.
  - STOP entry or STOP loss: broker fee plus exchange taker fee.
  - TP LIMIT: broker fee only.
  - Time-stop or manual close by marketable order: broker fee plus exchange taker fee.

| Futures type | MOEX taker fee |
| --- | ---: |
| Currency contracts | `0.00462%` |
| Interest contracts | `0.01650%` |
| Stock contracts | `0.01980%` |
| Index contracts | `0.00660%` |
| Commodity contracts | `0.01320%` |

- The H4A research/runtime model uses the official MOEX asymmetrical tariff logic: maker exchange fee is `0`, taker exchange fee depends on the contract type table above.

## Fill-Dependent Recalculation
- `H4A` uses the actual fill as the anchor.
- Effective stop is wider than the setup stop because `sl_rr=2.5`.
- Effective TP is derived from widened risk because `tp_rr=0.6`.
- This means the final live TP/SL levels can differ from the static levels seen before fill.
- Operator must confirm the realized fill, then recalculate the active bracket immediately.
- Telegram follow-up must carry the recalculated packet:
  - effective fill,
  - initial loss stop,
  - TP limit,
  - current protective stop,
  - break-even trigger and stop,
  - trailing trigger and offset,
  - time-stop deadline,
  - explicit `Confirm` action for each completed H4A step,
  - manual override action if execution leaves the baseline.

## Protective Stop Logic
- The stop is dynamic, not static.
- First phase: initial protective stop after fill.
- Second phase: break-even lift after `0.1R`.
- Third phase: trailing stop after `0.1R`, with `2`-tick offset from the best favorable price.
- Because of this, an `SL` exit in reports can be:
  - a true loss stop,
  - a near-break-even stop,
  - a profitable protective stop.

## Same-Bar Assumption
- Backtest tie-break rule: `same_bar_policy=open_direction`.
- This is a simulator rule, not a human instruction.
- In manual/live execution, use broker or exchange timestamps if both TP and stop seem touched in the same bar.
- If precise ordering cannot be reconstructed, record the event as `same_bar_ambiguous` in the operator note and treat post-trade analysis conservatively.

## Minimum Operator Checklist
1. Confirm entry corridor, estimated risk per lot, and planned quantity before sending the order.
2. Start a `10`-minute timer for every `H4A` LIMIT entry.
3. If no fill by `10` minutes, replace with a marketable order or abort and log the deviation as `entry_fallback_market` or `manual_override`.
4. Confirm the fallback decision in Telegram follow-up when the `10`-minute timeout is reached.
5. After fill, recalculate effective TP and active stop from the actual fill price.
6. Review the Telegram post-fill packet and confirm that the recalculated bracket matches the broker-side position.
7. Start a `180`-minute holding timer from the actual fill timestamp.
8. Move the stop to break-even plus buffer when `0.1R` is reached and confirm the Telegram follow-up.
9. Maintain the trailing stop with `2`-tick offset after activation and confirm the Telegram follow-up.
10. Log the exit reason explicitly.

## Recommended Exit Note Taxonomy
- `tp_limit`
- `initial_loss_sl`
- `protective_sl`
- `time_stop_180m`
- `same_bar_ambiguous`
- `entry_fallback_market`
- `risk_cap_granularity_exception`
- `manual_override`

## Non-Negotiable Constraint
- If the operator cannot monitor dynamic stop movement and timing rules, `H4A` should not be used as the manual profile for that session.
