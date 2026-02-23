---
name: preferences-presets-migrations
description: Use when implementing presets/preferences persistence (local + API), schemaVersioning, and migrations for module/layer settings.
---

## Goal
Persist module/layer state reliably across sessions and versions.

## Requirements
- Store `schemaVersion` for preferences and presets.
- Provide migration functions: vN -> vN+1.
- Merge strategy:
  - local cache fast load
  - then remote sync overwrite/merge based on timestamp or explicit rule
- Presets support:
  - apply absolute (replace current)
  - apply merge (apply deltas only)

## Safety
- Never crash on unknown keys; ignore safely.
- When a layer/module is removed in code:
  - migrations should drop or mark as deprecated

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
