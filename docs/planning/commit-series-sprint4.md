# Sprint 4 Commit Series Plan

## Goal
Split the current Sprint 4 delivery into atomic, reviewable commits with clear rollback boundaries.

## Commit order
1. `chore(config): add/adjust v2 and execution policy flags`
- Files: `configs/*`, `src/moex_carry/config.py`.

2. `feat(domain): add decision/pretrade/execution policy services`
- Files: `src/moex_carry/domain/*`, `src/moex_carry/pipeline.py`.

3. `feat(api): introduce v2 action/ops/research/rebalance surfaces and adapters`
- Files: `src/moex_carry/ui/app.py`, `src/moex_carry/storage/*`, `src/moex_carry/observability/*`.

4. `feat(ui): migrate workspaces and market/decision flows to backend-owned v2 state`
- Files: `ui-web/src/App.tsx`, `ui-web/src/features/**`, `ui-web/src/entities/**`, `ui-web/src/shared/api/**`.

5. `test(api-ui): add parity/contract/e2e coverage for v2 flows`
- Files: `tests/test_api_v2.py`, `tests/test_signal_api.py`, `tests/test_ui_api.py`, `ui-web/tests/*`.

6. `docs(runbooks): finalize sprint4 operations runbooks and patch notes`
- Files: `docs/runbooks/*`, `docs/release-notes.md`, `docs/planning/product-decisions.md`.

## Patch-note format (mandatory for each release entry)
1. `Summary`
2. `Changed`
3. `Verification`
4. `Risk / Rollback`
