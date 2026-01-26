# Release Notes

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
