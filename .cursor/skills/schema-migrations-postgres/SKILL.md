---
name: schema-migrations-postgres
description: >
  Postgres/PostGIS schema migrations and idempotent DB evolution. Use when adding/changing tables,
  columns, indexes, PostGIS geometry types, partitions, or when asked about migrations strategy.
---

# Postgres Schema Migrations

## Goal

Make DB schema changes reproducible, reviewable, and reversible (best-effort).

## Deliverables

* A migrations folder (e.g., `migrations/postgres/`) with ordered scripts.
* A migration runner command (Node or Python) wired into `package.json` scripts.
* Guidance: how to apply migrations locally and in CI.

## Workflow

1. Choose migration format:

   * SQL files with numeric prefix (recommended): `YYYYMMDDHHMM__desc.sql`
2. Add a schema version table if missing (e.g., `schema_migrations`).
3. For each change:

   * Write forward migration.
   * If feasible, write rollback (or document non-reversible).
4. PostGIS specifics:

   * For geometry columns: define SRID, type, and indexes.
   * Add GIST indexes for spatial query paths.
5. Update registry (if schema backs a domain object):

   * `registry/objects/*` fields/join details.
6. Add tests:

   * smoke test: connect to DB and ensure expected table/column exists.
7. Run:

   * migrations apply
   * `archctl validate`

## Definition of Done

* A fresh DB can be created to current schema by running migrations.
* Schema changes are not "hand-edited" in dev DB only.

## Guardrails

* No destructive migrations without explicit plan (backfill + rollout).
* Avoid breaking existing readers without versioning strategy.

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


