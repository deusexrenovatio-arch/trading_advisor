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

## Data integrity gate (mandatory before analysis/decisions)
- Treat data layers as strictly ordered:
  - source minutes: `data/output/intraday_minute_series/intraday_minute_series_<STOCK>_<FUTURE>.csv`
  - derived replay: `data/output/incremental_replay/<STOCK>__<FUTURE>.parquet`
  - derived projections: `data/output/unified/{top_pairs,signals,backtest_summary}.csv`
- Never compare metrics across mixed layers (for example source CSV days vs stale replay parquet metrics).
- Run integrity check before any signal-quality, PnL, or probability conclusions:
  - `python scripts/check_data_integrity.py --data-dir data --max-day-gap 2`
- Blocker conditions:
  - any stale replay pair (`source_days - replay_days > max_day_gap`);
  - replay range starts later than source range for the same pair;
  - replay max day is behind source max day.
- After backfill or historical corrections, force replay rebuild before analysis:
  - `POST /api/signals/refresh` with `{"force_full": true}` (or equivalent CLI flow),
  - wait until refresh status is not `busy`.
- If refresh is `busy`/`error`, do not use `fresh=true` API responses for final conclusions.

## Probability confidence gate (mandatory)
- Always report `forecast_n_effective` and `forecast_confidence_tier` with probability metrics.
- Treat `very_low`/`low` confidence as advisory only, not as hard production gate input.
- For production gate decisions, require at least `medium` confidence or explicit user override.

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

## First-time-right gate (mandatory)
- Scope:
  - Research decisions.
  - User-facing business logic (API/UI/runtime flows that affect user outcomes).
- Run `docs/checklists/first-time-right-gate.md`:
  - before implementation for non-trivial tasks,
  - before pre-push for changed behavior.
- Keep `configs/user_needs_catalog.yaml` updated when user-facing behavior or decision flow changes.
- CI enforces full acceptance-scenario coverage through `configs/user_needs_catalog.yaml`.

Blockers:
- Primary/edge/negative user scenarios not defined.
- Acceptance criteria or expected outputs are ambiguous.
- Long-running/network-heavy step has no budget and stop/replan trigger.
- Heavy task design does not include chunking/parallel/cache or resume strategy.
- Changes do not clearly map to the main objective or known user value.
- Repeated issue is being patched again without structured root-cause review.

Required report block for implementation and reviews:
1. Confirmed coverage.
2. Missing or risky scenarios.
3. Resource/time risks and chosen controls.
4. Highest-priority fixes or follow-ups.

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
- `python scripts/validate_user_needs_catalog.py`
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
- Windows lock workaround for `npm ci` (`EPERM` on `esbuild.exe`):
  - Bash: `MOEX_CARRY_SKIP_NPM_CI=1 git push`
  - PowerShell: `$env:MOEX_CARRY_SKIP_NPM_CI='1'; git push`

## Optional checks (manual / data-dependent)
- Data integrity parity:
  - `python scripts/check_data_integrity.py --data-dir data --max-day-gap 2`
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
