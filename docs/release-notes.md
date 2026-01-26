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
