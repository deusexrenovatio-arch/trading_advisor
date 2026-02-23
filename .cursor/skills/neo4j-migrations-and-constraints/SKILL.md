---
name: neo4j-migrations-and-constraints
description: >
  Neo4j schema management: constraints, indexes, and versioned Cypher migrations.
  Use when adding labels/relationships, changing KG model, adding unique constraints, or hardening graph integrity.
---

# Neo4j Migrations & Constraints

## Goal

Keep the Knowledge Graph consistent and performant under incremental evolution.

## Deliverables

* `migrations/neo4j/` with ordered Cypher scripts.
* A migration runner (Node/Python) that applies scripts idempotently.
* Baseline constraints/indexes for core labels: Document, Chunk, Image, Entity.

## Workflow

1. Define migration tracking:

   * store applied migration ids in a dedicated node or meta label.
2. For each KG model change:

   * Add constraints:

     * unique keys (e.g., Document(id, version), Chunk(chunk_id), Entity(canonical_id))
   * Add indexes for common traversals.
3. Update registry objects/relations if model changes affect contracts.
4. Add integrity checks:

   * ensure version chains exist (`UPDATES`)
   * ensure provenance links exist (`SOURCE`, `OF_DOCUMENT`)
5. Add minimal query tests (smoke):

   * can fetch a Document and traverse to Chunks and linked Entities.

## Definition of Done

* KG can be built from scratch with migrations.
* Queries do not degrade due to missing indexes/constraints.

## Guardrails

* Constraints must be safe for existing data (backfill or cleanup plan before applying).
* Avoid modeling "facts" without provenance links.

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


