---
name: index-vector
description: >
  Use when building or updating FAISS vector indices for document chunks or images.
  Covers embedding metadata, mapping to chunks, and index lifecycle.
---

# Index Vector (FAISS)

## Checklist
1) Registry-first: update `registry/datasets/vector_embeddings.yaml` and `registry/objects/Embedding.yaml`.
2) Define embedding model, dimension, and idempotency key (chunk_id + model + version).
3) Store embedding metadata alongside chunk/document IDs.
4) Ensure index rebuild and incremental update strategy (batch vs streaming).
5) Add a smoke test for nearest-neighbor queries.
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


