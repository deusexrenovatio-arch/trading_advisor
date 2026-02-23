---
name: release-notes-and-changelog
description: >
  Release process, changelog, and versioning. Use when preparing a release, tagging versions,
  generating release notes, setting SemVer, or implementing Conventional Commits-based changelog.
---

# Release Notes & Changelog

## Goal

Make releases explainable and reproducible.

## Deliverables

* `CHANGELOG.md` (or release notes file) maintained per release.
* Versioning strategy (SemVer):

  * major for breaking contracts
  * minor for backward-compatible features
  * patch for fixes
* Release checklist template.

## Workflow

1. Confirm what is a breaking change:

   * GraphQL field removal/rename
   * event schema breaking changes (major bump)
2. Ensure commit discipline:

   * Conventional Commits or equivalent.
3. Generate notes:

   * summarize changes by module and contract impact.
4. Tag release:

   * create annotated tag `vX.Y.Z`.
5. Add rollback notes:

   * how to revert, what is risky.

## Definition of Done

* Anyone can answer: "what changed in vX.Y.Z and why?"
* Breaking changes are clearly communicated.

## Guardrails

* No "silent breaking" in contracts/events.
* Release notes must mention registry/contract changes explicitly.

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


