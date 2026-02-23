---
name: archctl-policy-authoring
description: >
  Author or tighten archctl fitness rules and policy gates. Use when adding/adjusting fitness rules,
  preventing boundary violations, enforcing registry-first, "archctl policy", "policy gate", "CI blocking".
---

# Archctl Policy Authoring

## Goal

Turn architecture principles into enforceable gates (CI + local checks).

## Deliverables

* New/updated `archctl policy` rules that catch common violations:

  * GraphQL SDL changed -> registry objects/resolvers updated
  * Event schema changed -> versioning rules satisfied + module produces/consumes updated
  * New ingestion pipeline -> sources/datasets/quality/policies updated
  * Cross-module DB access forbidden without connector/data product
* Documentation of rules and examples in `docs/ARCHCTL_POLICIES.md` (or similar).

## Workflow

1. Enumerate violation classes:

   * contract changed without registry change
   * module boundary bypass
   * missing provenance fields
2. Encode each class into policy:

   * file path based rules (diff patterns)
   * dependency rules (module->module)
   * schema rules (version increment)
3. Add "why" messages:

   * failure output must tell the developer what to fix.
4. Add a minimal test set for policy:

   * sample diffs (fixtures) or unit tests for policy logic if archctl supports.
5. Integrate into CI:

   * ensure policy runs on PR.

## Definition of Done

* A PR that violates contract/registry discipline fails with actionable message.
* Policy rules are deterministic and do not require network.

## Guardrails

* Do not overfit rules to one scenario; keep them durable.
* Avoid blocking harmless refactors (bucket F/G) unless they change boundaries/contracts.

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


