# UI Web Module

## Scope
This document covers the React UI in `ui-web/` and the API endpoints it uses.

## UI components (`ui-web/src`)
- `App.tsx`
  - Orchestrates tabs and wires shared hooks/helpers.
  - Keeps render logic thin; business logic lives in feature hooks and shared utils.
- `features/decisions/*`
  - `DecisionsTab`, `DecisionTable`, `DecisionDetail`, `decisionColumns`, `useDecisionView`.
  - Server-side filters: strategy/instrument/risk/news/created range.
- `features/market/*`
  - `MarketTablesTab` + `useMarketTables` (Top pairs / Signals / Backtests tables, sorting, filters, details).
  - Wrapper tabs: `features/top-pairs/TopPairsTab`, `features/signals/SignalsTab`,
    `features/backtests/BacktestsTab`.
- `features/backtest-run/*`
  - `BacktestV2Tab`, `useBacktestForwardHpo` for param specs, run, and results.
- `features/forward/*`
  - `ForwardTab` for forward status.
- `features/hpo/*`
  - `HpoTab` leaderboard view and run form.
- `shared/ui/*`
  - Reusable UI pieces (KeyValueGrid, JsonBlock, GenericTable, ParamInput).
- `shared/utils/*`
  - Field/formatting helpers, date utils, param helpers, and backtest view helpers.
- `SpreadChart.tsx`
  - Plots spread_mid and spread_pct series with entry/exit annotations.
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
  - Includes spread_pct, rtc_pct, floor_rate_annual, score_floor, total_score, decision.
- `GET /api/signals/active`
  - Active signals derived from the latest run.
- `GET /api/signals/refresh-status`
  - Scheduler status and last successful recompute timestamp.
- `POST /api/signals/refresh`
  - Triggers an on-demand signal recompute; UI reload uses this endpoint.
- `GET /api/signals/history?from=YYYY-MM-DD&to=YYYY-MM-DD&limit=...`
  - Historical signal actions.
- `GET /api/signals/executions?stock=...&future=...&limit=...`
  - Execution history for a pair.
- `POST /api/signals/execute`
  - Logs a manual execution action.
- `GET /api/backtests?limit=...`
  - Backtest summary metrics.
- `GET /api/spread-series?stock=...&future=...&window_days=...&full_life=true|false`
  - Spread time series for charting.
  - `full_life=true` fetches the full contract life (current March/June futures).
  - Alpha metrics are shown in the details panel (not the main table).

## Parallel dev workflow
- Backend API (Flask) runs via `python -m moex_carry.cli ui` on `127.0.0.1:8050`.
- React UI runs via `npm run dev` in `ui-web/` on the Vite dev server.
- Vite is configured to proxy `/api` to the backend (`ui-web/vite.config.ts`).
- This keeps frontend and backend deployable separately while supporting parallel development.

## UI layout (screen-fit)
- Top pairs view uses a two-column layout on desktop:
  - Left: compact table (sticky header, condensed columns).
  - Right: details panel with tabs (Overview, Alpha, Liquidity, Execution).
- Mobile stacks into a single column with the details panel below the table.
- The details panel uses fixed-height charts (e.g., 280-320px) to avoid vertical overflow.
- Alpha metrics (tp/sl, p_hit_tp/p_hit_sl, sigma_h, half_life) appear only in the Details > Alpha tab.
- The main table stays focused on floor + decision visibility to fit the screen.

## Contract alignment
- The Decisions tab relies on the fields in `contracts/decision-view.schema.json`.
- The details panel renders `decision_log` as-is and assumes schema validity.
