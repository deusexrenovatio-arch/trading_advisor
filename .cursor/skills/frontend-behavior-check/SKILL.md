---
name: frontend-behavior-check
description: Verifies trading UI behavior via API smoke checks, Vite proxy validation, chart data checks, and basic table expectations. Use when frontend/UI/React/Vite/MUI table or chart changes are made, or when the user asks to validate the UI.
---

# Frontend Behavior Check

## Purpose
Quickly validate that the UI features work after frontend changes without relying on manual screenshots.

## When to use
- User mentions UI, frontend, dashboard, таблицы, графики, charts, Vite, React, MUI.
- After changing UI tables, filters, sorting, or chart logic.
- When the user asks to “проверить фронт”.

## Checklist

### 1) Backend health and API smoke checks
- Ensure the backend listens on port `8050`.
- If the port is occupied by multiple processes, stop only the processes bound to `8050`, then restart:
  - `python -m moex_carry.cli ui --config configs/default.yaml`
- Validate JSON responses (no HTML/NaN):
  - `/api/decision-view?limit=5` returns array
  - `/api/top-pairs?limit=5` returns array with `stock` and `future`
  - `/api/signals?limit=5` returns array with `signal_action`
  - `/api/backtests?limit=5` returns array

### 2) Spread-series chart data checks
- Pick the first pair from `data/output/top_pairs.csv`.
- Call `/api/spread-series?stock=...&future=...&window_days=60`.
- Verify fields exist and are JSON-valid:
  - `spread_mid`, `spread_pct`, `zscore`
  - `entry_flag`, `exit_flag`, `trade_cycle`
  - `trade_return_pct`, `trade_return_pct_net`, `trade_return_annual`, `trade_hold_days` (if exit events exist)
- If cached data is missing new fields, restart backend so cache is refreshed.

### 3) Vite proxy + UI expectations
- Identify the Vite port from the terminals log (look for `Local:`) and test proxy:
  - Current default: `http://127.0.0.1:5176/api/top-pairs?limit=5`
  - If different, update the port in this checklist.
- If proxy fails, restart Vite dev server.
- UI expectation checks (data-driven):
  - Top pairs / Signals / Backtests show rows (non-empty arrays).
  - Details panel for a pair returns spread-series data (non-empty).
  - Sorting should work on numeric columns (verify column exists and values are numeric).
  - Backtest v2 params show human labels (no technical keys with dots) and dict weights render as labeled rows.

### 4) Optional automated tests
- Run:
  - `python -m pytest tests/test_ui_api.py tests/test_spread_series.py`
- Report warnings but treat failures as blockers.

### 5) Process update (when adding UI functionality)
- Add/refresh test cases in `docs/test-cases.md`.
- Update acceptance checklist in `configs/acceptance_scenarios.yaml` and link `test_cases`.

## Report format
- **Backend**: ok/fail + error if any
- **API**: ok/fail per endpoint
- **Spread series**: ok/fail + missing fields if any
- **Proxy**: ok/fail + port used
- **UI expectations**: ok/fail (rows present, details data present)
- **Tests**: pass/fail + command

## Notes
- If any endpoint returns HTML, the backend process is stale or routing is wrong. Restart backend.
- If arrays are empty, data may be missing; ask whether to re-run compute/backtest pipeline.
