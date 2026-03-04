# Skill Governance Sync Workflow

## Purpose
- Keep local and global skill catalogs coordinated without weakening repository governance.
- Prevent skill drift after updates in `AGENTS.md`, `docs/DEV_WORKFLOW.md`, or first-time-right policy docs.
- Keep prompt context small by centralizing governance details in one workflow document.

## Scope and precedence
- Local catalog (`.cursor/skills`):
  - primary runtime catalog in this repository (includes mirrored global skills);
  - strict repository contract;
  - must include repository governance baseline block;
  - must pass `python scripts/validate_skills.py`.
- Global catalog (`$CODEX_HOME/skills` or `%USERPROFILE%\\.codex\\skills`):
  - source catalog used for mirror refresh into local repository skills.
- Precedence in this repository:
  1. `AGENTS.md` and `docs/DEV_WORKFLOW.md`
  2. local `.cursor/skills/*/SKILL.md`

## Mandatory repository baseline for every invoked skill
- Run `./scripts/worktree_guard.ps1 -Action Check` before edits/long commands (run `Init` when missing/expired).
- Run `python scripts/run_lean_gate.py` before and after meaningful patches.
- Keep `plans/PLANS.yaml`, `memory/agent_memory.yaml`, and `docs/session_handoff.md` aligned with real progress.
- Run `python scripts/validate_session_handoff.py` after handoff updates.
- Run `python scripts/validate_task_request_contract.py` after updating task contract and first-time-right report blocks.
- Ensure `## Repetition Control` is present in handoff and incident learning fields follow `configs/agent_incident_policy.yaml`.
- Before push, run blocker checks from `docs/DEV_WORKFLOW.md`, including `python scripts/validate_quality_scorecards.py`.
- For repeated issues/regressions, run `docs/checklists/first-time-right-gate.md` and produce the required 4-part report block.

## Context budget rule
- Keep `AGENTS.md` skill list compact (name + path mapping only).
- Keep `SKILL.md` governance blocks short and reference this document instead of duplicating command catalogs.
- Expand details only when running the specific skill workflow.

## Update trigger
Run this workflow when any of these change:
- `AGENTS.md`
- `docs/DEV_WORKFLOW.md`
- `docs/checklists/first-time-right-gate.md`
- `docs/runbooks/governance-remediation.md`
- `scripts/run_lean_gate.py`
- global skill content under `$CODEX_HOME/skills` that must be mirrored locally

## Update procedure
1. Identify changed governance requirements in source-of-truth docs.
2. Mirror missing/updated global skills from `$CODEX_HOME/skills` into `.cursor/skills`.
3. Sync repository baseline block across all local `SKILL.md` files.
4. Keep domain-specific sections intact; change only lifecycle/governance instructions.
5. Refresh `AGENTS.md` skill list so it matches local `.cursor/skills`.
6. Validate local catalog:
   - `python scripts/validate_skills.py`
7. Run governance loop:
   - `python scripts/run_lean_gate.py`
8. Record durable state updates:
   - `plans/PLANS.yaml`
   - `memory/agent_memory.yaml`
   - `docs/session_handoff.md`

## Automated decision gate
Run this step before patching any skill files:
- Input: changed files (`git diff --name-only HEAD`) and optional change intent text.
- Command: `python scripts/skill_update_decision.py --request "<intent>" --from-git --json`
- Output decision:
  - `UPDATE_EXISTING`: intent clearly overlaps one existing skill or there is direct local/global skill edit.
  - `ADD_NEW`: no existing skill has sufficient overlap.
  - `NO_CHANGE`: insufficient signal; requires human scoping.
- Machine gates:
  - `evidence_source_docs`:
    - Pass when governance sources changed (`AGENTS.md`, `docs/DEV_WORKFLOW.md`, etc.).
  - `existing_skill_target`:
    - Pass when `.cursor/skills/<skill>/SKILL.md` is directly touched.
  - `global_mirror`:
    - Pass when global catalog path changes (`%USERPROFILE%\.codex\skills` / `$CODEX_HOME/skills`).
  - `coverage_strength`:
    - Pass/Warning/Fail based on overlap score between request/domain tokens and skill metadata.
  - `ambiguity`:
    - Warn when two or more skills have close overlap; treat as manual review case.
- If `coverage_strength` fails and no source-doc/governance trigger: default to `ADD_NEW`.
- If `existing_skill_target` or `global_mirror` passes: default to `UPDATE_EXISTING` and enforce full update path from this workflow.
- Decision matrix:
  - `UPDATE_EXISTING` (high confidence) when one is true:
    - Direct local skill edit (`existing_skill_target`).
    - Governance source/docs changed (`governance_scope` / `evidence_source_docs` pass).
    - Global catalog edit (`global_mirror`).
    - Strong overlap and clear winner (`coverage_strength >= 0.45` and `ambiguity` gap >= 0.16).
  - `ADD_NEW` (medium confidence) when no direct target and overlap is weak (`coverage_strength < 0.25`).
  - `NO_CHANGE` when overlap is ambiguous or request context is incomplete.
- Output reason map:
  - `evidence_source_docs`: why repo-level context changed.
  - `coverage_strength`: whether intent/skills lexical overlap is sufficient.
  - `ambiguity`: why a tie or close match needs manual review.
- Required follow-up:
  - `UPDATE_EXISTING`: apply baseline sync path then run `python scripts/validate_skills.py`.
  - `ADD_NEW`: run onboarding flow (`skill-creator` -> `skill-installer`) and update `AGENTS.md`.
- Optional enforcement:
  - When committing, pre-commit hook `/.githooks/pre-commit` runs:
    - `python scripts/skill_precommit_gate.py` for changed files.
    - blocks commit when output is `NO_CHANGE` (without explicit scope).
    - emits suggested `SKILL_UPDATE_INTENT` for ambiguous intent.
  - Local override for commit runs:
    - `SKILL_DECISION_GATE=0 git commit ...` (skip guard).
    - `SKILL_DECISION_STRICT=1 git commit ...` (also blocks `ADD_NEW` decisions).

## Non-goals
- Do not hardcode repository-specific command lists into all global skills.
- Do not skip local governance because a global skill suggests a different flow.
