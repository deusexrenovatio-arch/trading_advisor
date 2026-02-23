---
name: patch-series-splitter
description: >
  Split large AI-generated diffs into a clean patch series (registry -> contracts -> code -> tests -> docs).
  Use when changes are too big, PR is hard to review, or user asks to "split commits" / "make atomic commits".
---

# Patch Series Splitter

## Goal

Convert "one big AI diff" into reviewable commits.

## Deliverables

* A commit plan (ordered list) and resulting commits:

  1. registry
  2. contracts
  3. implementation
  4. tests
  5. docs
* Optional: multiple PR plan if change is large.

## Workflow

1. Build a commit plan:

   * list files per commit category
2. Apply staging strategy:

   * use `git add -p` and commit per category
3. Ensure each commit passes basic checks where possible:

   * registry commit -> `archctl validate` (if available)
   * implementation commit -> tests (if available)
4. If a change set is inherently huge:

   * split into PR1 (registry+contracts) and PR2 (implementation+tests+docs)

## Definition of Done

* Each commit is revertible and has one responsibility.
* Review can happen commit-by-commit.

## Guardrails

* Do not reorder changes that violate Registry-First (registry must be first).
* Avoid "format-only" commits mixed with functional changes.

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


