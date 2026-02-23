---
name: tz-oss-scout
description: Evaluate technical specs/TZ or architecture briefs, decompose into capability blocks, review functional coverage and NFR gaps, scout OSS options, and produce an auditable buy-vs-build report with a shortlist, scoring, and POC plan. Use when a new spec arrives, during architecture or sprint planning, or when minimizing custom development via OSS selection.
---

# TZ OSS Scout

## Overview
Use this skill to turn a technical spec into a buy-vs-build report with an OSS shortlist and POC plan. Produce a single report using `references/report-template.md`.

## Inputs
- Collect the spec text or stabilized fragment.
- Capture target platform/stack, if known.
- Capture constraints: license policy, on-prem/cloud, compliance/audit requirements, banned tech.
- If any input is missing, proceed with explicit assumptions and ask focused follow-ups.

## Workflow
1. Normalize the spec
   - Extract users/actors, scenarios, data objects, integrations, and constraints.
   - List undefined terms, missing metrics, and ambiguous statements.
2. Decompose capabilities
   - Break into capability blocks with inputs/outputs, dependencies, and criticality.
   - Use `references/capability-glossary.md` as a starting list.
3. Review functional requirements
   - Classify items as Must/Should/Could.
   - Propose acceptance criteria and high-level test ideas for key items.
4. Review NFRs and risks
   - Fill the NFR checklist and record gaps.
   - Create a risk table with Impact/Likelihood/Mitigation/Owner.
5. Scout OSS per capability
   - Find 2-5 candidates per capability.
   - Record maturity signals: release cadence, maintainer count, issue activity.
   - Capture license, integration effort, and potential pitfalls.
6. Score and shortlist
   - Apply `references/oss-scoring-rubric.md`.
   - Enforce hard blockers; assign Adopt / Adopt with constraints / Reject.
7. Synthesize buy vs build
   - Recommend what to adopt vs build, and why.
   - Minimize custom code; keep differentiators explicit.
8. Define POC plan
   - Time-box the POC and set success criteria and exit conditions.
9. Record assumptions and decisions
   - List assumptions explicitly.
   - Maintain decision log and traceability from requirements to choices.

## Output requirements
- Follow `references/report-template.md` exactly.
- Keep one report with auditable decisions, explicit assumptions, and traceability.

## Guardrails
- Prefer OSS over custom build unless a hard blocker exists.
- Stay skeptical: popularity is not fitness.
- Optimize for total cost of ownership, not stack aesthetics.
- Avoid proposing new dependencies without clear justification and license fit.

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
