# Development Workflow

## Goals
- Catch regressions early across backend + UI.
- Keep contract changes visible and reviewed.
- Make checks repeatable locally and in CI.

## Required checks (CI + local)

### Backend (Python)
- `python -m pip install -e ".[dev]"`
- `pytest`

### Frontend (UI)
- `cd ui-web`
- `npm ci`
- `npm run lint`
- `npm run build`

## Optional checks (manual / data-dependent)
- Acceptance smoke: `python scripts/acceptance_check.py`
  - Requires backend at `http://127.0.0.1:8050` and UI at `http://127.0.0.1:5176`
  - Scenarios live in `configs/acceptance_scenarios.yaml`
- E2E UI: `cd ui-web && npm run test:e2e`
  - Requires backend running with data
- Demo pipeline: `python scripts/build.py`

## Branching model
- `main` is protected; work happens on short-lived branches.
- Branch naming: `feat/`, `fix/`, `docs/`, `test/`, `chore/`, `refactor/`.
- Prefer linear history via rebase or squash before merge.

## Commit message rules (Conventional Commits)
- Format: `type(scope): summary`
- Types: `feat`, `fix`, `docs`, `test`, `chore`, `refactor`, `perf`, `ci`, `build`, `revert`.
- Scopes (recommended): `backend`, `ui-web`, `strategy`, `risk`, `data`, `contracts`,
  `configs`, `scripts`, `tests`, `docs`, `ci`.
- Split commits by concern (registry -> contracts -> code -> tests -> docs).
- CI enforces commit messages for PRs via commitlint.

Examples:
- `feat(strategy): add aggregation summary`
- `fix(ui-web): guard empty history table`
- `docs(contracts): document decision_view fields`

## When to add tests
- Bug fix: add a regression test in `tests/` or `ui-web/tests/`.
- Contract changes: update the schema + tests + acceptance scenario.

## Architecture gate (TODO)
- Archctl is not configured yet. When added, CI should run:
  - `archctl validate`
  - `archctl policy --from <base> --to <head>`
