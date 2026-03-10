# AGENTS.md for d:\New Project

<INSTRUCTIONS>
## Intent (Harness-Oriented)
- This file is a routing map, not a full handbook.
- Keep context small and rely on mechanical checks.
- Reference philosophy: https://openai.com/index/harness-engineering/

## Hot Source of Truth
- `docs/agent/entrypoint.md`
- `docs/agent/domains.md`
- `docs/agent/checks.md`
- `docs/agent/runtime.md`
- `docs/agent/skills-routing.md`
- `docs/README.md`
- `docs/DEV_WORKFLOW.md`
- `docs/workflows/context-budget.md`
- `docs/workflows/skill-governance-sync.md`
- `docs/session_handoff.md`
- `harness-guideline.md`
- `CODEOWNERS`

## Warm and Cold Source of Truth
- Warm: runbooks, architecture deep dives, workflows.
- Cold: `plans/`, `memory/`, archives, artifacts, skill catalog.
- Full skill catalog path: `docs/agent/skills-catalog.md`.

## Non-Negotiable Loop
1) Verify worktree context with `./scripts/worktree_guard.ps1 -Action Check`.
2) Before non-trivial implementation, fill task contract in `docs/session_handoff.md`.
3) Validate contract: `python scripts/validate_task_request_contract.py`.
4) Before and after meaningful patches run `python scripts/run_lean_gate.py`.
5) Keep `plans/PLANS.yaml` and `memory/agent_memory.yaml` aligned with durable decisions.
6) Keep `docs/session_handoff.md` valid via `python scripts/validate_session_handoff.py`.
7) Before push run blockers from `docs/DEV_WORKFLOW.md`, including `python scripts/validate_quality_scorecards.py`.
8) Any failing gate is a blocker; fix first using `docs/runbooks/governance-remediation.md`.

## PR-Only Main Policy
- Use PR-only flow for `main`: feature branch -> PR -> merge.
- Direct push to `main` is blocked by `.githooks/pre-push`.
- Emergency override requires both:
  - `MOEX_CARRY_EMERGENCY_MAIN_PUSH=1`
  - `MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON='<ticket/incident>'`

## Skills
- Mandatory flow starts with `parallel-worktree-flow`.
- Use matching skills in the same turn when user names a skill or intent clearly matches.
- Do not carry skills across turns unless re-mentioned.
- Skill governance workflow: `docs/workflows/skill-governance-sync.md`.
- Validate skill mapping with `python scripts/validate_skills.py`.

## First-Time-Right Protocol
- Applies to research and user-facing business logic.
- Run `docs/checklists/first-time-right-gate.md` before implementation and pre-push.
- Required report block:
  1) Confirmed coverage.
  2) Missing or risky scenarios.
  3) Resource/time risks and controls.
  4) Highest-priority fixes or follow-ups.

## Task Request Contract
- For non-trivial tasks, maintain in `docs/session_handoff.md`:
  - `## Task Request Contract`
  - `## First-Time-Right Report`
  - `## Repetition Control`
- Validate with `python scripts/validate_task_request_contract.py`.

## Worktree Safety Protocol
- Before code edits or long commands:
  - `./scripts/worktree_guard.ps1 -Action Check`
- If context missing or expired:
  - `./scripts/worktree_guard.ps1 -Action Init -WorktreePath "<path>" -Branch "<branch>" -ContextTtlHours 12`
- If mismatch is reported, stop and switch to expected worktree/branch.
</INSTRUCTIONS>
