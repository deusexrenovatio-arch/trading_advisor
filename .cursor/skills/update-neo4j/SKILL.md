---
name: update-neo4j
description: >
  Use when adding or modifying knowledge graph nodes/edges in Neo4j, including
  document-entity links, versioning, and graph provenance rules.
---

# Update Neo4j (Knowledge Graph)

## Checklist
1) Registry-first: update `registry/datasets/knowledge_graph.yaml` and relevant objects.
2) Define node labels and relationships (Document, Chunk, Image, Entity).
3) Persist provenance links (Fact -> Document, Chunk -> Document).
4) Maintain version chains (`Document {id, version}` -> UPDATES).
5) Add graph integrity checks and a minimal query test.
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


