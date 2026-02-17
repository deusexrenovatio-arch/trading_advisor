---
name: frontend-behavior-check
description: Verifies trading UI behavior via API smoke checks, Vite proxy validation, chart data checks, and table expectations. Use after frontend/UI/React/Vite/MUI changes, during regression rechecks, and as a pre-push gate for UI branches. Use together with trading-ui-dashboard and ui-decision-log when UI contracts or projections are touched.
---

# Frontend Behavior Check

## Purpose
Quickly validate that UI behavior and API contracts stay correct after frontend changes.

## Skill dependencies and lifecycle gates
- Start phase for UI work: run `parallel-worktree-flow` first.
- Build/change phase: use with `trading-ui-dashboard`; add `ui-decision-log` if projection fields change.
- Recheck phase: rerun this skill after UI bug fixes and before closing regression tasks.
- Pre-push phase: do not mark UI work complete until required checks from `docs/DEV_WORKFLOW.md` pass.

## Checklist

### 1) Backend health and API smoke checks
- Ensure backend listens on port `8050`.
- If the port is occupied by multiple processes, stop only the processes bound to `8050`, then restart:
  - `python -m moex_carry.cli ui --config configs/default.yaml`
- Validate JSON responses (no HTML/NaN):
  - `GET /api/v2/decisions/view?limit=5` returns array (or adapter `GET /api/decision-view?limit=5`)
  - `GET /api/v2/top-pairs?limit=5` returns array with `stock` and `future`
  - `GET /api/v2/signals/active?limit=5` returns array with `signal_action`
  - `GET /api/backtests?limit=5` returns array

### 2) Spread-series chart data checks
- Pick the first pair from `data/output/top_pairs.csv`.
- Call `GET /api/spread-series?stock=...&future=...&window_days=60`.
- Verify fields exist and are JSON-valid:
  - `spread_mid`, `spread_pct`, `zscore`
  - `entry_flag`, `exit_flag`, `trade_cycle`
  - `trade_return_pct`, `trade_return_pct_net`, `trade_return_annual`, `trade_hold_days` (if exits exist)
- If cached data is missing new fields, restart backend to refresh cache.

### 3) Vite proxy + UI expectations
- Identify Vite port from terminal log (`Local:`) and test proxy:
  - Default: `http://127.0.0.1:5176/api/v2/top-pairs?limit=5`
  - If different, update this checklist for current branch/worktree.
- If proxy fails, restart Vite dev server.
- Verify UI expectations:
  - Top pairs / Signals / Backtests render rows (non-empty arrays or expected empty-state UI).
  - Pair details panel returns non-empty spread-series data.
  - Numeric column sorting works where numeric values are present.
  - Backtest v2 params show human labels (no raw dotted keys) and dict weights render as labeled rows.

### 4) Mandatory local gate before push
- Run backend and docs checks:
  - `python scripts/sync_architecture_map.py --check`
  - `python -m pytest tests/test_ui_api.py tests/test_spread_series.py`
- Run frontend checks:
  - `npm --prefix ui-web ci`
  - `npm --prefix ui-web run lint`
  - `npm --prefix ui-web run build`
- Treat any failure as blocker for push.

### 5) Optional data-dependent checks
- Acceptance smoke:
  - `python scripts/acceptance_check.py`
- UI E2E:
  - `npm --prefix ui-web run test:e2e`

### 6) Process updates (when adding UI functionality)
- Add or refresh relevant cases in `docs/test-cases.md`.
- Update `configs/acceptance_scenarios.yaml` and ensure `test_cases` links are correct.

## Report format
- Backend: ok/fail + error.
- API smoke: ok/fail by endpoint.
- Spread series: ok/fail + missing fields.
- Proxy: ok/fail + port used.
- UI expectations: ok/fail.
- Required gate: pass/fail + commands.

## Notes
- If any endpoint returns HTML, backend process or routing is stale. Restart backend.
- If arrays are empty due missing data, explicitly state whether pipeline recompute is required.
