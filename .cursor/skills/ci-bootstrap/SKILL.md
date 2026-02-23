---
name: ci-bootstrap
description: >
  Bootstrap CI/CD and merge gates for this repo. Use when asked to add CI, required checks, fitness rules,
  GitHub Actions/GitLab CI, "pipeline", "gating", "archctl validate", "archctl policy", "tests on PR",
  or when the repo has checks described but not implemented.
---

# CI Bootstrap

## Goal

Make merges safe and repeatable: every PR must pass the same minimum checks (architecture + tests + lint).

## Non-negotiables

* CI MUST run `archctl validate` and `archctl policy --from <base> --to <head>` on every PR.
* CI MUST run tests for touched stacks (Node + Python) when applicable.
* Fail fast: architecture gates before long test jobs.

## Deliverables

* Minimal CI config (prefer GitHub Actions, otherwise GitLab CI) with:

  * archctl validate
  * archctl policy (impact/policy)
  * JS tests + typecheck/lint (if present)
  * Python tests (if present)
* PR merge requirements documented in `/docs/DEV_WORKFLOW.md` (or similar).

## Workflow

1. Detect CI platform:

   * If `.github/workflows` exists -> GitHub Actions.
   * If `.gitlab-ci.yml` exists -> GitLab CI.
   * Else create GitHub Actions by default.
2. Detect package manager:

   * If `pnpm-lock.yaml` -> pnpm.
   * Else if `package-lock.json` -> npm.
   * Else if `yarn.lock` -> yarn.
3. Add CI steps:

   * Install deps (Node + Python when relevant).
   * `npm run archctl validate` (or `npm run archctl -- validate` if needed).
   * `archctl policy --from <base> --to <head>` (use git refs from CI).
   * Run tests:

     * Node: `npm test` (existing) + optional `lint`/`typecheck` if scripts exist.
     * Python: run `pytest` in modules that have `requirements.txt` + tests (skip if absent).
4. Add caching:

   * Node cache: `~/.npm` or pnpm store.
   * Python cache: pip cache.
5. Add "required checks" note:

   * Document which checks are required before merge.
6. Add a smoke job:

   * `npm run dev` is NOT required in CI; keep CI deterministic.

## Definition of Done

* New PR triggers CI automatically.
* A failing `archctl validate` blocks merge.
* A contract change without registry updates fails (via policy).
* CI results are visible and consistent across runs.

## Guardrails

* Do not add heavyweight tooling if minimal is enough.
* If a check is described in docs but not implementable yet, add it as TODO + issue, not as fake passing job.

## Skill dependencies and lifecycle gates
- Start phase: use this skill at the beginning of the matching task stream.
- Recheck phase: rerun this skill after meaningful fixes or behavior changes in its scope.
- Pre-push phase: run required checks from `docs/DEV_WORKFLOW.md` and treat failures as blockers.

## Repository governance baseline (mandatory)
- Follow `docs/workflows/skill-governance-sync.md` for mandatory repository gates (worktree guard, lean loop, plans/memory/handoff, pre-push blockers, repeated-issue escalation).
- Keep this skill focused on domain workflow; do not duplicate repository governance details here.
## Mandatory pre-push guidance
- Run `python scripts/sync_architecture_map.py --check` when boundaries or integrations are touched.
- Run required checks from `docs/DEV_WORKFLOW.md` for touched areas; treat failures as blockers.
- If contracts/registry/docs changed, update source-of-truth artifacts before push and keep notes in AGENTS or PR summary.


