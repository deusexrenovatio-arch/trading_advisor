# UI Web Module

## Scope
This document covers the React UI in `ui-web/` and the API endpoints it uses.

## UI components (`ui-web/src`)
- `App.tsx`
  - Tabs: Decisions, Top pairs, Signals, Backtests.
  - Decision grid with filters (strategy, instrument, risk, news).
  - Decision details panel (raw `decision_log` JSON).
  - Tables for top pairs, signals, and backtests with sorting and filters.
  - Signal execution panel with execution history.
- `SpreadChart.tsx`
  - Plots spread and z-score series with entry/exit annotations.
- `main.tsx`
  - App bootstrap, MUI theme, global CSS.

## API dependencies
The UI expects these endpoints (served by the Python backend in
`src/moex_carry/ui/app.py`):

- `GET /api/decision-view?limit=...`
  - Returns `decision_view` records for the decision grid.
  - Optional filters: `strategy_type`, `primary_instrument`, `risk_state`,
    `news_severity`, `created_from`, `created_to`.
- `GET /api/decision-log/{decision_id}`
  - Returns the raw `decision_log` record for the details panel.
- `GET /api/decisions/{decision_id}/action`
  - Returns operator action and execution status for the decision.
- `POST /api/decisions/{decision_id}/action`
  - Records approve/reject and creates an execution request.
- `GET /api/top-pairs?limit=...&all=true|false`
  - Top ranked pairs with signal metadata.
- `GET /api/signals/active`
  - Active signals derived from the latest run.
- `GET /api/signals/history?from=YYYY-MM-DD&to=YYYY-MM-DD&limit=...`
  - Historical signal actions.
- `GET /api/signals/executions?stock=...&future=...&limit=...`
  - Execution history for a pair.
- `POST /api/signals/execute`
  - Logs a manual execution action.
- `GET /api/backtests?limit=...`
  - Backtest summary metrics.
- `GET /api/spread-series?stock=...&future=...&window_days=...`
  - Spread time series for charting.

## Contract alignment
- The Decisions tab relies on the fields in `contracts/decision-view.schema.json`.
- The details panel renders `decision_log` as-is and assumes schema validity.
