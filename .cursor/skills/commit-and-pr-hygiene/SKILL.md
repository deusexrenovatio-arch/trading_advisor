---
name: commit-and-pr-hygiene
description: >
  Git hygiene for AI-assisted development. Use when asked about commit messages, splitting changes,
  atomic commits, PR structure, PR templates, "clean history", "squash", "Conventional Commits",
  "AI generated code", or before opening a PR.
---

# Commit & PR Hygiene (AI-native)

## Goal

Keep history readable and reversible even when AI generates large diffs.

## Non-negotiables

* Prefer small PRs.
* No mixed concerns in one commit (registry + contracts + code + tests + docs should be separate commits).
* Never merge code that changes contracts without registry updates.

## Commit sequencing (recommended)

1. `chore(registry): ...` (registry-first)
2. `chore(contracts): ...` (GraphQL/event schemas)
3. `feat|fix(<module>): ...` (implementation)
4. `test(<module>): ...` (tests)
5. `docs: ...` (docs-sync / architecture notes)

## Deliverables

* Commit messages in Conventional Commits style: `type(scope): summary`
* PR description with:

  * What changed / Why
  * Impact (modules, contracts, data)
  * Risk & rollout plan
  * Verification (commands run)
  * Checklist (registry/contracts/tests/observability/docs)

## Workflow

1. Classify change (AGENTS buckets A-G).
2. Stage changes by area (use `git add -p`):

   * registry first
   * contracts next
   * code next
   * tests next
   * docs last
3. Write commit messages:

   * Use meaningful scope: module id (e.g., `reserves-prototype`, `gis-api`, `graphql-gateway`).
   * Include issue id if exists (e.g., `refs #123`).
4. PR structure:

   * If change touches A-E (module/object/event/schema/integration), require "Impact" section.
   * If PR > ~400 LOC, split into multiple PRs unless justified.

## Definition of Done

* `git log --oneline` tells a coherent story.
* Reviewer can revert one concern without collateral damage.
* PR description contains verification commands and impact summary.

## Failure modes to avoid

* "One giant commit" from AI with registry/contracts/code/tests mixed.
* Messages like "fix" / "update".
* PR that changes GraphQL without registry/resolvers/objects updated.

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


