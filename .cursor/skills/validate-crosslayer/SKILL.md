---
name: validate-crosslayer
description: >
  Use when verifying consistency across Postgres, Neo4j, and FAISS layers:
  Document <-> Chunk <-> Embedding <-> Entity links and provenance completeness.
---

# Validate Cross-Layer Consistency

## Checklist
1) Confirm every Document has at least one Chunk and version metadata.
2) Confirm every Chunk has an Embedding (or explicit exclusion reason).
3) Confirm Knowledge Graph links Document/Chunk to at least one Entity.
4) Validate provenance: document_id + version + source_id reachable from all layers.
5) Produce a coverage report (counts + missing links).
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


