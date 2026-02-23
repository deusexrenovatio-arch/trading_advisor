---
name: ingest-postgres
description: >
  Use when implementing or changing document ingestion into Postgres tables
  (documents, document_chunks, document_images). Covers schema, idempotency,
  provenance, and registry updates.
---

# Ingest Postgres (Documents)

## Checklist
1) Registry-first: update `registry/sources`, `registry/datasets`, and `registry/objects`.
2) Define tables and migrations for `documents`, `document_chunks`, `document_images`.
3) Ensure idempotency keys and versioning for `document_id + version`.
4) Store provenance references (source_id, version, ingest_run_id).
5) Add unit tests for parsing/chunking and basic integrity checks.
6) Run `archctl validate` and update docs if registry changed.

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


