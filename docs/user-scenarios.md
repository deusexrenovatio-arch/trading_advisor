# User Scenarios

## US-01 Configure the strategy
Actor: Operator
Goal: Define rates, costs, and risk limits for StockFuturesSpreadCarryAlpha.
Steps:
1. Open config (configs/default.yaml or environment overrides).
2. Set r_cb_annual and confirm r_fund_annual/r_disc_annual inherit by default.
3. Define cost, liquidity, and alpha thresholds.
Expected:
- Config loads without validation errors.
- Defaults are explicit and documented.

## US-02 Daily scan of pairs
Actor: Operator
Goal: Get ranked pairs with floor + alpha metrics.
Steps:
1. Run compute pipeline or signal cycle.
2. Open Top pairs view.
Expected:
- Pairs are ranked by total_score.
- Each row includes spread_pct, rtc_pct, floor_rate_annual, score_floor, score_alpha.

## US-03 Drill into a pair
Actor: Operator
Goal: Inspect spread history and entry/exit flags.
Steps:
1. Open Top pairs and select a row.
2. View the spread series chart.
Expected:
- Series contains spread_mid and spread_pct.
- Entry/exit markers align with strategy rules.

## US-04 Enter a position (floor + alpha)
Actor: Operator
Goal: Enter when floor_pass and liquidity_pass are true.
Steps:
1. Confirm decision flag ENTER_OK.
2. Execute trade with suggested quantities and exec prices.
Expected:
- TradeSignal records action=ENTER and reason codes.

## US-05 Early exit (alpha)
Actor: Operator
Goal: Exit within H days after favorable spread move.
Steps:
1. Monitor spread_pct vs TP_net.
2. Trigger exit when TP or SL conditions hit.
Expected:
- TradeSignal records action=EXIT with reason TP/SL.

## US-06 Hold to expiry or roll
Actor: Operator
Goal: Maintain floor carry when alpha exit does not trigger.
Steps:
1. Hold position until close_buffer_days.
2. Roll to next expiry if roll rules pass.
Expected:
- TradeSignal records action=EXIT with reason EXPIRY or ROLL.

## US-07 Backtest review
Actor: Operator
Goal: Validate share of alpha exits and holding profile.
Steps:
1. Run backtest pipeline.
2. Review backtest metrics.
Expected:
- Metrics include share_alpha_exits and avg_hold_days.

## US-08 Risk/liquidity rejection
Actor: Operator
Goal: Understand why a pair is skipped.
Steps:
1. Open ranked list with decision flags.
2. Inspect skip reason and liquidity metrics.
Expected:
- Decision indicates SKIP_* with traceable thresholds.
