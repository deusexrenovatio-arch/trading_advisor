# Development Workflow

## Goals
- Catch regressions early across backend + UI.
- Keep contract changes visible and reviewed.
- Make checks repeatable locally and in CI.

## Mandatory worktree preflight
- Before any code change, lock expected worktree + branch for the current session:
  - `./scripts/worktree_guard.ps1 -Action Init -WorktreePath "D:\\wt-<name>" -Branch "<branch>" -ContextTtlHours 12`
- Before every development task, verify context:
  - `./scripts/worktree_guard.ps1 -Action Check`
- Inspect current vs expected context:
  - `./scripts/worktree_guard.ps1 -Action Show`
- Reset context when switching streams:
  - `./scripts/worktree_guard.ps1 -Action Clear`

Policy:
- If `Check` fails, stop development actions immediately.
- Fix by switching to the correct worktree/branch or re-running `Init` with explicit user-approved values.
- Local context file `.worktree-context.local.json` is intentionally ignored by git.
- Context lock expires automatically (`ContextTtlHours`, default `12`) and must be re-initialized for a new session.

## Required checks (CI + local)

### Backend (Python)
- `python -m pip install -e ".[dev]"`
- `python scripts/sync_architecture_map.py --check`
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
- Frontend behavior check (API + proxy + spread-series):
  - Follow `D:/New Project/.cursor/skills/frontend-behavior-check/SKILL.md`
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
- UI refactors: refresh `docs/test-cases.md` and acceptance scenarios to preserve coverage.

## Architecture gate (TODO)
- Archctl is not configured yet. When added, CI should run:
  - `archctl validate`
  - `archctl policy --from <base> --to <head>`
