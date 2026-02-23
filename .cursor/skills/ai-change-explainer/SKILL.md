---
name: ai-change-explainer
description: >
  Produce an explainable change summary for PRs with AI-generated diffs. Use when preparing PR descriptions,
  summarizing impact, explaining registry/contract changes, or when asked "what changed and why".
---

# AI Change Explainer

## Goal

Turn a large diff into a human-readable, auditable explanation.

## Deliverables

* PR summary block with sections:

  1. Intent (why)
  2. Registry changes
  3. Contract changes (GraphQL/events)
  4. Code changes by module
  5. Data/lineage impact
  6. Risks & mitigations
  7. Verification (commands/tests run)
  8. Rollout/rollback notes

## Workflow

1. Identify touched areas:

   * registry, contracts, services, tools, docs
2. For each area:

   * describe what changed in plain language
   * state expected behavior change
3. Call out risks:

   * breaking changes
   * data migrations
   * performance / cost (OCR)
4. List verification steps that were run or must be run.

## Definition of Done

* A reviewer can approve/deny based on summary without reverse-engineering the diff.

## Guardrails

* Do not claim tests were run if they were not.
* Be explicit about assumptions and unknowns.

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


