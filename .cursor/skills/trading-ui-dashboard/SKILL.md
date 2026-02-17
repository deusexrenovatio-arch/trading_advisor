---
name: trading-ui-dashboard
description: Build production-grade trading advisor UI with React/Vite/TypeScript, MUI, and AG Grid. Use when improving dashboard readability, decision tables, filters, drill-down, or API-backed UI behavior. Co-use with ui-decision-log for projection changes and frontend-behavior-check for recheck/pre-push validation.
---

# Trading UI Dashboard (React + MUI + AG Grid)

## Quick start
- Default stack: React + Vite + TypeScript + MUI + AG Grid.
- Primary data source: `decision_view` list, `decision_log` for drill-down.
- Keep `decision_id` as the unique row key.

## Skill dependencies and lifecycle gates
- Start phase: run `parallel-worktree-flow` first when opening a new UI stream.
- Projection phase: run `ui-decision-log` when `decision_log` -> `decision_view` mapping changes.
- Recheck phase: run `frontend-behavior-check` after each UI fix/refactor.
- Pre-push phase: run required checks from `docs/DEV_WORKFLOW.md` plus UI behavior checks.

## Core requirements
1) Table readability
- Pin `created_at`, `decision_id`, `action`, `risk_state`.
- Use numeric formatting for prices, PnL, rates, and percentages.
- Use concise headers and tooltips for long names.
- Use conditional styles for `risk_state`, `action`, `news_severity`.

2) Filtering and search
- Global quick filter.
- Column filters for `strategy_type`, `primary_instrument`, `risk_state`, `news_severity`.
- Date range filter on `created_at`.

3) Drill-down
- Row click opens right-side detail panel.
- Show raw `decision_log` JSON with copy/download.
- Always link details to `decision_id`.

4) Performance
- Use pagination or infinite row model.
- Memoize column definitions and value formatters.
- Avoid heavy computations inside cell renderers.

## Data/API guidance
- Prefer API endpoints over browser reads from JSONL files.
- Recommended endpoints:
  - `GET /api/v2/decisions/view` (primary)
  - `GET /api/decision-view` (adapter compatibility)
  - `GET /api/decision-log/{decision_id}`
- Keep contracts aligned with:
  - `contracts/decision-view.schema.json`
  - `contracts/decision-log.schema.json`

## Field and parameter metadata
- Use `fieldMeta`, `formatValue`, `getFieldLabel`, and `getFieldTooltip` as source of truth.
- Tooltip format: `Formula: ... Interpretation: ...`.
- For Backtest v2 params, use `paramMeta` with human labels and labeled rows for dict values.

## Layout recommendation
- Top toolbar: time range, quick filter, refresh.
- Main area: decision table.
- Side panel: decision details plus key metrics.

## AG Grid starter config (example)
```tsx
const columnDefs = [
  { field: "created_at", headerName: "Time", pinned: "left" },
  { field: "decision_id", headerName: "Decision", pinned: "left" },
  { field: "strategy_type", headerName: "Strategy", filter: true },
  { field: "primary_instrument", headerName: "Instrument", filter: true },
  { field: "action", headerName: "Action" },
  { field: "risk_state", headerName: "Risk" },
  { field: "news_severity", headerName: "News" },
  { field: "cost_summary.round_trip_cost", headerName: "Cost" },
  { field: "backtest_metrics.max_drawdown", headerName: "Max DD" }
];
```

## UI theming defaults
- Dense table rows and compact typography.
- Use monospaced font for IDs.
- Color mapping:
  - `risk_state`: green/yellow/red
  - `action`: approve/reject/hold

## Validation checklist
- `decision_id` is unique and visible.
- Filters and quick search reduce rows correctly.
- Drill-down shows exact `decision_log` for selected row.
- Table remains readable at 1920x1080.
- Local gate commands pass:
  - `npm --prefix ui-web run lint`
  - `npm --prefix ui-web run build`
  - `python scripts/sync_architecture_map.py --check`

## Avoid
- Do not compute trading decision logic in UI.
- Do not mutate `decision_log` or `decision_view` in client code.
