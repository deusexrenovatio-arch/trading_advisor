# H4A Manual Execution Baseline

## Scope
Operator contract for the current morning-plan intraday futures execution baseline.

## Baseline Status
- Current runtime baseline: `H4A_CAP_OFF`.
- Practical meaning: this is not only "profit-cap off".
- The live baseline is the inherited `O1` trade-management package plus `max_profit_rr=0.0`.
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

## Fill-Dependent Recalculation
- `H4A` uses the actual fill as the anchor.
- Effective stop is wider than the setup stop because `sl_rr=2.5`.
- Effective TP is derived from widened risk because `tp_rr=0.6`.
- This means the final live TP/SL levels can differ from the static levels seen before fill.
- Operator must confirm the realized fill, then recalculate the active bracket immediately.

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
1. Confirm entry corridor and planned quantity before sending the order.
2. Start a `10`-minute timer for every `H4A` LIMIT entry.
3. If no fill by `10` minutes, replace with a marketable order or abort and log the deviation.
4. After fill, recalculate effective TP and active stop from the actual fill price.
5. Start a `180`-minute holding timer from the actual fill timestamp.
6. Move the stop to break-even plus buffer when `0.1R` is reached.
7. Maintain the trailing stop with `2`-tick offset after activation.
8. Log the exit reason explicitly.

## Recommended Exit Note Taxonomy
- `tp_limit`
- `initial_loss_sl`
- `protective_sl`
- `time_stop_180m`
- `same_bar_ambiguous`
- `entry_fallback_market`
- `manual_override`

## Non-Negotiable Constraint
- If the operator cannot monitor dynamic stop movement and timing rules, `H4A` should not be used as the manual profile for that session.
