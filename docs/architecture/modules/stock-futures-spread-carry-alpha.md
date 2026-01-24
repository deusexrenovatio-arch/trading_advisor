# Stock Futures Spread Carry Alpha

## Scope
Defines the StockFuturesSpreadCarryAlpha strategy module that replaces the legacy
carry + z-score spread logic. The module targets two layers:
- Floor carry: hold to expiry if the hedged carry return meets the benchmark.
- Alpha exit: exit early (typically 5-20 trading days) when spread moves in favor.

The implementation keeps the existing pipeline, decision log, and UI contracts
stable while replacing internal calculations and signals.

## Inputs
- StockMarketPoint: timestamp, bid, ask, mid/close, volume, dollar_volume.
- FutMarketPoint: timestamp, bid, ask, mid/close, volume, open_interest.
- ContractSpec: multiplier, expiry, currency, tick_size.
- Rates: r_cb_annual, r_fund_annual, r_disc_annual (defaults tied to r_cb_annual).
- Dividends: list of (ex_date, amount) for the stock.
- Execution costs: fees, slippage, and tick size.
- Risk limits: capital base mode, notional limits, margin buffers.

## Outputs
- PairRankingRow: ranked scanner output with floor/alpha metrics and flags.
- TradeSignal: ENTER/HOLD/EXIT with quantities, exec prices, and reason codes.
- Decision metadata: spread_pct, rtc_pct, floor_rate_annual, score_* values.

## Submodules

### CalendarAndTime
- Computes DTE and year fraction (tau).
- Supports ACT/365 and ACT/360; optional trading-day mode.

### DividendModel
- Computes DivSum and PVDiv for events in (t, Texp].
- Uses exp(-r_disc * tau) discounting.

### ExecutionModel
- Converts quotes into executable prices with slippage.
- Falls back to close/last if bid/ask is missing.

### CostModel
- Computes fees and round-trip costs per share and per contract.
- Supports fee per share or bps for stocks and per-contract fees for futures.

### SpreadCalculator
- SpreadMid = (S_mid - PVDiv) - F_mid.
- SpreadPct = Spread / S_mid.
- Entry/exit exec spreads use execution prices.

### FloorYieldCalculator
- Computes FloorPnL and FloorRate_annual on capital base.
- Gate: FloorRate_annual >= r_cb_annual - floor_tolerance.

### LiquidityMetrics
- Computes spread bps, dollar volume, and days-to-exit.
- Gate: bid/ask, volume, and OI thresholds (fallback to volume if OI missing).

### SpreadStatsAndAlphaMetrics
- Computes spread volatility on horizon H.
- Computes MFE/MAE and P_hitTP / P_hitSL.
- Computes RTC in spread units and optional half-life.

### PairScoringAndRanking
- Combines floor score, alpha score, and penalties into TotalScore.
- Produces decision flags: ENTER_OK or SKIP_*.

### StrategyEngine
- Enters only when floor_pass and liquidity_pass.
- Exits on TP/SL/time-stop/expiry/roll with explicit reason codes.

### BacktestEvaluator (optional)
- Replays the same logic to validate alpha exits and floor hold behavior.

## Integration points
- `pipeline.compute_pairs` produces PairRankingRow and CSV outputs.
- `ui` reads `top_pairs.csv` and spread-series API for charts.
- `decision_log` stores new strategy metadata for auditability.
- Backtests must match the same cost and execution assumptions.

## Fallback rules
- Missing bid/ask: use close/last as mid; slippage still applied.
- Missing open interest: liquidity gate ignores OI for that leg.
- Missing dividends: PVDiv = 0 and DivSum = 0.
