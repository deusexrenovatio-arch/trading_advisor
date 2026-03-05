# Development Workflow

## Goals
- Catch regressions early across backend + UI.
- Keep contract changes visible and reviewed.
- Make checks repeatable locally and in CI.
- Keep team context overhead bounded and machine-checked.

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
- Combined catalog handling for this repository:
  - Use local `.cursor/skills` as the primary runtime catalog (including mirrored global skills).
  - Mirror global updates from `$CODEX_HOME/skills` into `.cursor/skills` using `docs/workflows/skill-governance-sync.md`.
  - Always apply repository governance baseline from `AGENTS.md` and `docs/workflows/skill-governance-sync.md`.
  - Only local `.cursor/skills` are CI-gated by `python scripts/validate_skills.py`.
- Before editing a skill, run deterministic intent routing:
  - `python scripts/skill_update_decision.py --from-git --request "short reason/intent"`.
  - If the command returns `UPDATE_EXISTING`, patch existing skill(s); if `ADD_NEW`, follow new-skill onboarding via `.cursor/skills/skill-creator/SKILL.md` and `.cursor/skills/skill-installer/SKILL.md` when needed.
- Commit-time enforcement:
  - `.githooks/pre-commit` runs `python scripts/skill_precommit_gate.py` for staged skill/governance files.
  - Commit is blocked when decision is `NO_CHANGE`.
  - Use `SKILL_UPDATE_INTENT="<intent>"` for explicit routing and `SKILL_DECISION_STRICT=1` to also fail `ADD_NEW`.
- Start of any new development stream:
  - Run `.cursor/skills/parallel-worktree-flow/SKILL.md`.
- UI stream (`ui-web`, API projection, dashboard behavior):
  - Run `.cursor/skills/trading-ui-dashboard/SKILL.md`.
  - Run `.cursor/skills/ui-decision-log/SKILL.md` when `decision_log`/`decision_view` projection changes.
  - Run `.cursor/skills/frontend-behavior-check/SKILL.md` on recheck and before push.
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

## Task request contract gate (mandatory)
- Before non-trivial implementation, define operator contract in `docs/session_handoff.md`:
  - `## Task Request Contract` with objective, scope, constraints, done-evidence, and priority rule.
  - `## First-Time-Right Report` using the required 4-part report block.
  - `## Repetition Control` with max same-path attempts, stop trigger, reset action, new search space, and next probe.
- Use checklist:
  - `docs/checklists/task-request-contract.md`
- Validation command:
  - `python scripts/validate_task_request_contract.py`

Blockers:
- Missing measurable objective or contradictory scope.
- Missing completion evidence commands/artifacts.
- Missing priority rule when tradeoffs conflict.
- Missing repetition-control policy for stop/reset/new-search behavior.

## Context budget gate (mandatory)
- Keep handoff state in `docs/session_handoff.md`, not in long chat recaps.
- `## Current Delta` must stay within 8 bullets and contain only actionable changes.
- Do not copy large instruction catalogs into handoff or status updates.
- Validation command:
  - `python scripts/validate_session_handoff.py`
- Policy and usage:
  - `docs/workflows/context-budget.md`

## Coverage mapping
- Manual process acceptance scenarios:
  - `dev-skill-start-gate` -> `TC-DEV-WF-001`
  - `dev-skill-recheck-gate` -> `TC-DEV-WF-002`
  - `dev-skill-prepush-gate` -> `TC-DEV-WF-003`
- Detailed definitions:
  - `docs/test-cases.md`
  - `configs/acceptance_scenarios.yaml`

## Lean loop (default while coding)
- Use progressive disclosure: load only the files/slices required for the active step.
- Run fast governance loop after each meaningful patch:
  - `python scripts/run_lean_gate.py`
- On gate failure, use deterministic remediation map:
  - `docs/runbooks/governance-remediation.md`
- Keep machine-readable plan state fresh:
  - update `plans/PLANS.yaml` for active/completed/deferred status changes.
  - schema/invariants: `docs/planning/plans-registry.md`
- Keep operational memory fresh:
  - record durable decisions/incidents/patterns in `memory/agent_memory.yaml`.
  - incident `remediation_type` must follow `configs/agent_incident_policy.yaml`.
  - for incidents on/after policy effective date, include learning fields:
    - `incident_signature`,
    - `prevention_change`, `prevention_artifact`, `prevention_check`,
    - `loop_breaker_trigger`, `search_space_reset`, `same_path_attempts`.
- Keep handoff delta fresh:
  - update `docs/session_handoff.md` with current goal, delta, blockers, and next step.
  - keep task request contract and first-time-right report sections current.
- Keep diffs single-concern and short-lived; defer side-work to separate follow-ups.
- Before push/PR, always run the full blocker gate below.

## Dependency decision gate (ADR)
- Any dependency manifest change or high-impact abstraction change must include ADR update.
- ADR location:
  - `docs/architecture/adr/`
- Gate command:
  - `python scripts/validate_dependency_decisions.py`

## Required checks (CI + local)
- Treat this list as a blocker gate for pre-push and PR readiness.

### Backend (Python)
- `python -m pip install -e ".[dev]"`
- `python scripts/run_lean_gate.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_quality_scorecards.py`
- `python scripts/validate_python_style.py`
- `python scripts/validate_structured_logging.py`
- `python scripts/validate_codeowners.py`
- `pytest`

### Frontend (UI)
- `cd ui-web`
- `npm ci`
- `npm run lint`
- `npm run build`
- `npm run test:e2e` (CI required; local run before major UI merges)

## Automatic pre-push gate (recommended)
- Enable repository hooks once per clone:
  - `python scripts/install_git_hooks.py`
- This installs `core.hooksPath=.githooks` and runs required backend/frontend checks on `git push`.
- Any failed required check blocks push.
- Direct push to `main` is blocked (PR-only).
- Required merge path:
  - create short-lived feature branch,
  - push feature branch,
  - open PR,
  - merge PR into `main`.
- Emergency override for direct `main` push (incident/hotfix only, with explicit reason):
  - Bash: `MOEX_CARRY_EMERGENCY_MAIN_PUSH=1 MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON='<ticket/incident>' git push`
  - PowerShell: `$env:MOEX_CARRY_EMERGENCY_MAIN_PUSH='1'; $env:MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON='<ticket/incident>'; git push`
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
  - Follow `.cursor/skills/frontend-behavior-check/SKILL.md`
- E2E UI: `cd ui-web && npm run test:e2e`
  - Requires backend running with data
- Demo pipeline: `python scripts/build.py`

## Flaky test policy (blocking for governance)
- Policy source:
  - `configs/flaky_policy.yaml`
  - `docs/runbooks/flaky-tests-policy.md`
- Validation:
  - `python scripts/validate_flaky_policy.py`
- Rules:
  - no silent ignores,
  - bounded retries,
  - quarantine must have owner + issue + TTL + SLA.

## Ownership routing (blocking for governance)
- Source:
  - `CODEOWNERS`
  - `configs/codeowners_policy.yaml`
- Validation:
  - `python scripts/validate_codeowners.py`
- Rule:
  - governance, architecture, contracts, code, and CI paths must have deterministic owners.

## Local observability stack (recommended)
- Compose profile:
  - `docker-compose.observability.yml`
- Start:
  - `docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d`
- Docs:
  - `docs/runbooks/local-observability-stack.md`

## Scheduled maintenance (CI)
- `docs-gardening` workflow runs weekly and on manual trigger:
  - `python scripts/run_lean_gate.py`
  - `python scripts/doc_gardening_report.py`
  - `python scripts/autonomy_kpi_report.py`
- `agent-review` CI job publishes deterministic findings artifact for each PR/push:
  - `python scripts/agent_review.py`
- `governance-dashboard` CI job publishes one combined artifact:
  - `python scripts/build_governance_dashboard.py`
- `self-heal` workflow runs daily and on manual trigger:
  - `python scripts/self_heal.py`
  - if remediation fails, escalate via `docs/runbooks/self-heal-escalation.md`.

## Branching model
- `main` is protected; work happens on short-lived branches.
- PR-only merge policy for `main` is mandatory; no regular direct pushes.
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

