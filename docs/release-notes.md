# Release Notes


## 2026-01-26 - Stage 4: Trade Returns & UI Metrics

Added
- Trade PnL cash, net return (pre-tax), annualized return, and hold days in spread series.
- Average annualized return over last 5 exits for Top Pairs.
- UI table column and Alpha detail field for average annual return.
- UI trade summary line now shows pnl/net/annual/hold per cycle.
- Acceptance + UI tests updated to enforce new field.

Notes
- Net returns are pre-tax (dividend/profit taxes not applied in series).
- Reload recomputes signals on fresh market data and may differ from cached/top_pairs.


## 2026-01-26 - Stage 1: Contracts and Config

Added
- Portfolio domain dataclasses: PairSpec, DailyInstrumentBar, SnapshotPerPair, PositionState, PortfolioState, Order, Fill.
- Backtest/forward/HPO request contracts and ParameterSpec contract.
- Config resolver with AUTO resolution, cost stress multiplier, and validations.
- Parameter spec registry and `/api/params/specs` endpoint.
- Tests for resolver, parameter specs, and API endpoint.

Notes
- No changes to backtest/forward/HPO business logic.
- No changes to decision_log or decision_view schemas.

## 2026-01-26 - Stage 2: Calculations and SnapshotBuilder

Added
- Execution model support for BID/ASK and OHLC synthetic pricing with bps/tick slippage.
- Cost model helpers for fee per share/contract and round-trip cost/RTC percent.
- Dividend PV and funding cost helpers with day-count support.
- Spread/floor/liquidity calculations wired for SnapshotBuilder.
- SnapshotBuilder to assemble SnapshotPerPair universe with exec spreads, rtc_pct, floor metrics, and liquidity flags.
- Unit tests covering execution OHLC, dividends PV, margin-aware floor, and snapshot builder.

Notes
- Strategy, rebalance, and backtest business logic unchanged.

## 2026-01-26 - Stage 3: PortfolioRebalanceController

Added
- Portfolio rebalance controller implementing hard exits, TP/SL, rotation, band-rebalance, and turnover caps.
- Allocation methods: EQUAL, SCORE_WEIGHTED, SCORE_RISK_PARITY, FLOOR_PLUS_ALPHA_OVERLAY.
- Rebalance contracts (RebalanceConfig, RebalanceResult, TargetPosition) and portfolio utilities.
- Portfolio tests covering exits, hysteresis, rotation, band-rebalance, turnover cap, and risk-parity weights.

Notes
- Backtest engine and decision_log/decision_view schemas unchanged.
