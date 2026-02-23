---
name: rbac-layer-gating
description: Use when adding RBAC gating for modules/layers (UI + data + map enforcement) based on permissions/scopes.
---

## Goal
Ensure unauthorized layers cannot be loaded or rendered, even if UI state is wrong.

## Rules
- Registry defines requiredPermissions at module and/or layer level.
- Enforce RBAC in 3 places:
  1) UI: hide or disable with explanation
  2) DataLayer: do not run queries without permission
  3) MapController: do not add layers/sources without permission

## Deliverables
- authz state in store (permissions/scopes)
- selector helpers: isModuleAllowed, isLayerAllowed
- diagnostics reason: RBAC denied
- tests for gating behavior

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
