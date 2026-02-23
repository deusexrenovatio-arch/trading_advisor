---
name: codeowners-from-registry
description: >
  Generate and maintain CODEOWNERS based on registry ownership (owner_team / owner module).
  Use when asked about code ownership, review routing, CODEOWNERS, owner_team, or when adding modules.
---

# CODEOWNERS from Registry

## Goal

Make review routing deterministic and aligned with registry source-of-truth.

## Deliverables

* Generated `CODEOWNERS` (or updated) mapping:

  * `services/<module>/**` -> owning team
  * `registry/**` -> platform owners (or designated team)
  * `docs/**` -> platform or docs owners
* A generator script (Node) under `tools/` (preferred) or `tools/archctl/` integration.

## Workflow

1. Read module ownership from `registry/modules/**/module.yaml`:

   * `owner_team` and optionally data steward.
2. Define team mapping strategy:

   * `owner_team: platform` -> `@org/platform`
   * `owner_team: prototype` -> `@org/prototype`
   * If mapping unknown, write TODO and default to `@org/platform`.
3. Generate CODEOWNERS sections:

   * One section per module.
   * Stable ordering (alphabetical by module_id).
4. Add a validation step:

   * CI job fails if CODEOWNERS is out of sync with registry (optional but recommended).
5. Document update rule include in `/docs/DEV_WORKFLOW.md`.

## Definition of Done

* A PR touching `services/<module>` requests review from the expected owners automatically.
* Adding a module via `module-scaffold` results in CODEOWNERS update.

## Guardrails

* Avoid manual edits to CODEOWNERS; regenerate from registry.
* Keep team handles configurable (org name varies).

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


