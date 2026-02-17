# Development Workflow

## Goals
- Catch regressions early across backend + UI.
- Keep contract changes visible and reviewed.
- Make checks repeatable locally and in CI.

## Skill invocation gates (mandatory)
- Start of any new development stream:
  - Run `D:/New Project/.cursor/skills/parallel-worktree-flow/SKILL.md`.
- UI stream (`ui-web`, API projection, dashboard behavior):
  - Run `D:/New Project/.cursor/skills/trading-ui-dashboard/SKILL.md`.
  - Run `D:/New Project/.cursor/skills/ui-decision-log/SKILL.md` when `decision_log`/`decision_view` projection changes.
  - Run `D:/New Project/.cursor/skills/frontend-behavior-check/SKILL.md` on recheck and before push.
- Strategy/risk stream:
  - Run `intraday-futures-trading-advisor` + `moex-instruments-costs` + `risk-profile-gates`.
  - Add `news-geopolitics-filter` for event risk and `spread-arbitrage` for spread pair logic.
- Research/performance stream:
  - Run `ml-backtest-hpo-lab`.
  - Add `minute-candle-performance` for minute/high-load runtime changes.
- Recheck and pre-push:
  - Re-run the active stream verification skill(s) and then run required checks below.

## Coverage mapping
- Manual process acceptance scenarios:
  - `dev-skill-start-gate` -> `TC-DEV-WF-001`
  - `dev-skill-recheck-gate` -> `TC-DEV-WF-002`
  - `dev-skill-prepush-gate` -> `TC-DEV-WF-003`
- Detailed definitions:
  - `docs/test-cases.md`
  - `configs/acceptance_scenarios.yaml`

## Required checks (CI + local)
- Treat this list as a blocker gate for pre-push and PR readiness.

### Backend (Python)
- `python -m pip install -e ".[dev]"`
- `python scripts/sync_architecture_map.py --check`
- `python scripts/validate_test_cases.py`
- `python scripts/validate_skills.py`
- `pytest`

### Frontend (UI)
- `cd ui-web`
- `npm ci`
- `npm run lint`
- `npm run build`

## Automatic pre-push gate (recommended)
- Enable repository hooks once per clone:
  - `python scripts/install_git_hooks.py`
- This installs `core.hooksPath=.githooks` and runs required backend/frontend checks on `git push`.
- Any failed required check blocks push.
- Direct push to `main` is blocked by default.
- One-time override for emergency/admin pushes:
  - Bash: `MOEX_CARRY_ALLOW_MAIN_PUSH=1 git push`
  - PowerShell: `$env:MOEX_CARRY_ALLOW_MAIN_PUSH='1'; git push`

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
