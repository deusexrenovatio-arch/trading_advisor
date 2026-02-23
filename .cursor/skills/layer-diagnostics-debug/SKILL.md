---
name: layer-diagnostics-debug
description: Use when implementing layer diagnostics ('why not visible') and Debug UI that reports gates, errors, counts, and map existence.
---

## Goal
Make every layer debuggable in 30 seconds.

## Required diagnostics reasons
- zoom < minZoom
- RBAC denied
- style not ready
- source missing
- layer missing
- 0 features returned (empty dataset)
- limit reached (zoom in / tighten filters)
- last error (status/message)

## UI expectations
- Debug module shows a table of layers with:
  - enabled/visible
  - gate status + reasons
  - featureCount
  - lastParams (bboxKey, filters)
  - lastError

## Implementation notes
- Diagnostics must be computed from a single selector function (not scattered in components).
- Diagnostics must be stable across style changes and rehydration.

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
