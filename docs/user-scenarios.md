# User Scenarios

Reference:
- End-to-end operator flow for `Signals` is documented in `docs/signals-business-process.md`.

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
Actor: User
Goal: See the current state of spread signals and top pairs.
Steps:
1. Run the signal cycle or wait for the scheduled refresh.
2. Open Top pairs and Signals views.
3. Click Reload to trigger recompute and refresh rankings and signals.
4. Open pair Details to confirm snapshot_as_of and signal timestamps.
5. In Signals details, open tab `Сигнал` and check grouped trading plan blocks.
Expected:
- Pairs are ranked by total_score.
- Each row includes spread_pct, rtc_pct, floor_rate_annual, score_floor, score_alpha.
- Signals list includes actionable entries with timestamp and execution plan fields:
  - entry spread corridor (`entry_spread_pct_min/max`),
  - spread TP/SL levels (`tp_spread_pct_level`, `sl_spread_pct_level`),
  - forecast exit horizon (`forecast_exit_days`).
- Signal details show grouped plan sections:
  - `Контекст сигнала`,
  - `План входа`,
  - `Риск и стоп-уровни`,
  - `Прогноз выхода`.
- If API does not provide plan fields (`entry_*`, `tp/sl`, `forecast_*`) for a row, the UI shows a coverage hint and keeps the screen readable without empty/broken tabs.
- UI shows last successful recompute time.
- snapshot_as_of and signal timestamps reflect the latest run time using ISO 8601 with timezone (e.g., 2026-01-26T18:45:00Z).

## US-03 Drill into a pair
Actor: Operator
Goal: Inspect spread history and entry/exit flags.
Steps:
1. Open Top pairs and select a row.
2. View the spread series chart.
Expected:
- Series contains spread_mid and spread_pct.
- Entry/exit markers align with strategy rules.
- Tooltip timestamps match the snapshot_as_of time (ISO 8601 with timezone).

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
1. Run backtest v2 via UI (Backtest v2 tab) or CLI (`moex-carry backtest_v2`) or API (`POST /api/backtest/run`).
2. Review summary metrics, equity curve, and trades.
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

## US-09 Forward cycle
Actor: Operator
Goal: Run the forward paper loop with EOD -> OPEN -> after close persistence.
Steps:
1. Initialize the forward run (`POST /api/forward/start` or `moex-carry forward_start`).
2. Inspect status (`GET /api/forward/status` or `moex-carry forward_status`) or use the Forward status UI tab.
3. Run the forward paper engine at EOD to create next-open orders.
4. Run the OPEN phase to simulate fills and persist trades.
5. Run the after-close phase to mark to market and append equity.
Expected:
- State store persists portfolio and open orders across restarts.
- Trades are appended on OPEN fills.
- Equity curve appends one point per day.
- Alerts are emitted for missing data, wide spreads, or drawdown breaches.

## US-10 HPO run
Actor: Quant Researcher
Goal: Optimize strategy parameters using Backtest v2 as a black box.
Steps:
1. Define a search space for strategy parameters (e.g., z_window, TP_pct, SL_pct).
2. Configure walk-forward folds with embargo and choose evaluation mode (CONTINUOUS or WARMUP_THEN_FLAT).
2.1 (Optional) Set optimization metric (e.g., CAGR, IR, MaxDD) and mode (max/min).
3. Start an async HPO run (HPO UI tab submits `/api/hpo/run`).
3.1 (Optional) Provide a full JSON request in the HPO tab; it becomes the source of truth and overrides the form.
4. Poll `/api/hpo/status` (UI auto-refresh) until status changes to completed or failed.
5. Inspect the leaderboard when status is completed.
Expected:
- Folds respect train/val/test boundaries and embargo gaps.
- Objective penalizes violations and returns -INF on constraint breaches.
- HPO run returns run_id and progress counters.
- Status transitions: running -> completed (or failed with error).
- Leaderboard sorts by objective and best_config matches the top entry.

## US-11 Review decisions with server filters
Actor: Operator
Goal: Narrow the decisions list using server-side filters for faster reviews.
Steps:
1. Open Decisions tab.
2. Set Strategy/Instrument/Risk/News filters and a Created from/to date range.
3. Refresh.
Expected:
- API uses server-side filters (`strategy_type`, `primary_instrument`, `risk_state`, `news_severity`, `created_from`, `created_to`).
- Result list updates quickly without client-side heavy filtering.
