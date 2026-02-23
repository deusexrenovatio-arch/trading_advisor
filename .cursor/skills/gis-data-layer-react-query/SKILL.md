---
name: gis-data-layer-react-query
description: Use when adding bbox/filter GIS fetching with unified caching, cancellation, TTL, and error contract via TanStack React Query.
---

## Goal
Standardize GIS data fetching for map layers.

## Contract
Each fetch must return:
- data (GeoJSON or normalized payload)
- meta: featureCount, limitReached, bboxKey, filters
On error:
- { kind, status, message, endpoint, params }

## Rules
- Query key MUST include: layerId, bboxKey/extentKey, relevant filters, auth scope if needed.
- Must support AbortSignal for cancellation on viewport changes.
- Must implement staleTime/cacheTime appropriate for map panning.
- Must handle common failure modes:
  - 404/HTML instead of JSON
  - empty result (0 features) is not an error
  - limit reached should surface as limitReached, not silent empty

## Deliverables
- query functions per module (e.g., ndogd)
- error mapping helper
- extentKey helper (quantize bbox)
- tests for queryKey generation and error mapping

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
