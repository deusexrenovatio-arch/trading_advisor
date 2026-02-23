---
name: release-notes
description: "Create or update release note fragments and full release texts for this repo; use when asked for release notes, release text, changelog, or to satisfy CI release-note checks on PRs."
---

# Release Notes

## Overview
Create release note fragments for PRs and full release texts for tags. Keep notes short, ASCII, and focused on user-visible changes.

## Workflow
1. Decide scope: PR fragment vs tagged release.
2. Create a PR fragment in `docs/releases.d/` using the script or template.
3. Create a tagged release note in `docs/releases/` using the release template.

## PR Fragment
- Use file name: `YYYY-MM-DD-short-title.md`.
- Run from repo root:
  `python C:\Users\Admin\.codex\skills\release-notes\scripts\new_release_fragment.py --slug "short-title"`
- Fill the template sections; remove a section only if it does not apply.

## Tagged Release
- Use file name: `docs/releases/vX.Y.Z.md`.
- Start from `assets/release-template.md`.
- Summarize user-visible changes, API/data changes, config changes, docs, and tests.

## CI Requirement
PRs must include at least one file in `docs/releases.d/*.md`. The CI job fails if no fragment is added.

## Resources
- `scripts/new_release_fragment.py`
- `assets/fragment-template.md`
- `assets/release-template.md`

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
