---
name: dependency-and-license-audit
description: >
  Dependency, vulnerability, and license audit for Node and Python. Use when adding/upgrading dependencies,
  security reviews, supply chain checks, "npm audit", "pip audit", "license", "allowlist/denylist".
---

# Dependency & License Audit

## Goal

Prevent supply-chain surprises: vulnerable deps and incompatible licenses.

## Deliverables

* Audit commands documented and runnable:

  * Node: `npm audit` (or pnpm/yarn equivalent)
  * Python: `pip-audit` (or alternative)
* License inventory + policy (allow/deny list)
* PR checklist item: "New dependency rationale + license check".

## Workflow

1. Detect ecosystems touched:

   * Node deps changed -> run Node audit
   * Python requirements changed -> run Python audit
2. Run audits and summarize:

   * critical/high vulnerabilities -> must fix or justify
3. License scan:

   * produce list of licenses for new deps
4. Record rationale:

   * why dependency is needed
   * alternatives considered
5. Update security docs if policy changes.

## Definition of Done

* New deps are reviewed for vulns and licenses.
* High severity issues are addressed before merge.

## Guardrails

* Do not add deps "because AI suggested it".
* Prefer existing libs already in stack.

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


