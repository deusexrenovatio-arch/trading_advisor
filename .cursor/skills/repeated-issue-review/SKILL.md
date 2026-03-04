---
name: repeated-issue-review
description: Deep troubleshooting and full component review when the same problem is reported across multiple messages, fixes fail, or the user asks for a full/detailed review. Use when repeated bug reports, regressions, "opyat"/"ne rabotaet", or requests to "razobratsya"/"polnyi review" appear.
---

# Repeated Issue Review

## Trigger Check
- Detect repeated complaints around the same issue across multiple messages or rising frustration.
- Treat as escalation: pause quick patches and do a structured review.

## Workflow
1) Reconstruct the problem history: what changed, what still fails, what logs/errors exist.
2) Reproduce logically: locate code paths, state transitions, side effects, persistence, and UI measurement.
3) Inventory likely failure points and rank them (data loss, async race, merge logic, measurement timing).
4) Collect evidence: API responses, UI state, cache/DB state; add minimal targeted logs only if needed.
5) Run a regression checklist for previously working functionality before declaring success.
6) Produce a "Findings + Hypotheses + Fix Plan" response before coding if root cause is unclear.
7) If confident, implement fixes and validate; avoid piecemeal changes.
8) If issue is repeated, add prevention update to operational memory with explicit behavior change and loop-breaker trigger.

## Output Requirements
- If the user asked for a review, follow the review format: findings first, severity order, file/line refs.
- Call out remaining risks and the minimal verification steps.
- Include regression checklist results and exact commands/URLs tested.
- Ask only essential questions needed to unblock progress.
- For repeated incidents, include:
  - incident signature (stable failure class id),
  - prevention change artifact (what changed in process/capability),
  - enforcement check (which gate/validator now blocks recurrence),
  - stop trigger and reset action for same-path repetition.

## Guardrails
- Prefer root-cause fixes over cosmetic workarounds.
- Keep changes minimal and scoped; avoid new dependencies.
- If multiple issues overlap, sequence fixes by: data persistence -> measurement/fit -> UI polish.
- Do not continue the same approach indefinitely: enforce capped attempts and shift to a new search space with explicit context reset.

## Regression Checklist (minimum)
- API smoke: key endpoints return JSON (no HTML/NaN).
- UI smoke: core tables load, detail/expand works, charts render.
- Data invariants: previously working fields still present and correctly formatted.

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
