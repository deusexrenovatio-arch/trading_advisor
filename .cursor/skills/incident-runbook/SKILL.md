---
name: incident-runbook
description: >
  Incident response runbooks and postmortems. Use when adding SLOs, alerts, external dependencies (OpenAI OCR),
  recurring failures, outages, "runbook", "incident", "postmortem", "on-call".
---

# Incident Runbook

## Goal

Make failures diagnosable in minutes, not hours.

## Deliverables

* Runbook in `docs/runbooks/<system>.md`:

  * symptoms
  * dashboards/metrics
  * logs to check
  * common root causes
  * remediation steps
* Postmortem template in `docs/postmortems/template.md`.

## Workflow

1. Identify critical flows:

   * ingestion jobs
   * OCR pipeline
   * GraphQL gateway
2. For each:

   * define top signals (latency, error rate, backlog)
   * define correlation id usage
3. Write remediation:

   * restart guidance
   * DLQ handling
   * fallback strategies
4. Add "when to escalate" criteria.

## Definition of Done

* A new engineer can follow the runbook to narrow root cause quickly.
* Postmortems are structured and produce action items.

## Guardrails

* Avoid vague runbooks ("check logs" is not a step).
* Prefer concrete commands and exact metric names.

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


