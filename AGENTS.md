# AGENTS.md for d:\New Project

<INSTRUCTIONS>
## Intent (Harness-Oriented)
- This file is a routing map, not a full handbook.
- Keep context small and rely on mechanical checks.
- Reference philosophy: https://openai.com/index/harness-engineering/
- Source-of-truth files:
  - `docs/README.md`
  - `docs/DEV_WORKFLOW.md`
  - `docs/workflows/context-budget.md`
  - `docs/workflows/agent-practices-alignment.md`
  - `docs/workflows/skill-governance-sync.md`
  - `docs/session_handoff.md`
  - `harness-guideline.md`
  - `plans/PLANS.yaml`
  - `memory/agent_memory.yaml`
  - `CODEOWNERS`
  - `docs/checklists/first-time-right-gate.md`
  - `docs/checklists/task-request-contract.md`
  - `docs/runbooks/governance-remediation.md`
  - `scripts/run_lean_gate.py`

## Non-Negotiable Loop
1) Verify worktree context with `./scripts/worktree_guard.ps1 -Action Check`.
2) Before implementation, define and validate task contract in `docs/session_handoff.md`.
  - use `docs/checklists/task-request-contract.md`.
  - include `## Repetition Control` (max attempts, stop trigger, reset action, new search space, next probe).
  - run `python scripts/validate_task_request_contract.py`.
3) Before and after meaningful patches run `python scripts/run_lean_gate.py`.
4) Keep `plans/PLANS.yaml` statuses aligned with actual progress.
5) Keep `memory/agent_memory.yaml` updated with durable decisions/incidents/patterns.
  - incidents must use remediation types from `configs/agent_incident_policy.yaml`.
  - incidents on/after policy effective date must include `incident_signature`, learning fields, and `same_path_attempts`.
6) Keep `docs/session_handoff.md` updated and pass `python scripts/validate_session_handoff.py`.
7) Before push run blocker checks from `docs/DEV_WORKFLOW.md`.
  - include `python scripts/validate_quality_scorecards.py`.
8) Use PR-only flow for `main`: feature branch -> PR -> merge.
  - direct push to `main` is blocked by `.githooks/pre-push`.
  - emergency override requires both:
    - `MOEX_CARRY_EMERGENCY_MAIN_PUSH=1`
    - `MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON='<ticket/incident>'`
9) Any failing gate is a blocker; fix first, continue after.
  - use `docs/runbooks/governance-remediation.md` for deterministic fixes.

## Skills
### Available skills
- ai-agent-architect: Repository skill. (file: .cursor/skills/ai-agent-architect/SKILL.md)
- ai-change-explainer: Repository skill. (file: .cursor/skills/ai-change-explainer/SKILL.md)
- archctl-policy-authoring: Repository skill. (file: .cursor/skills/archctl-policy-authoring/SKILL.md)
- architecture-review: Repository skill. (file: .cursor/skills/architecture-review/SKILL.md)
- business-analyst: Repository skill. (file: .cursor/skills/business-analyst/SKILL.md)
- ci-bootstrap: Repository skill. (file: .cursor/skills/ci-bootstrap/SKILL.md)
- codeowners-from-registry: Repository skill. (file: .cursor/skills/codeowners-from-registry/SKILL.md)
- commit-and-pr-hygiene: Repository skill. (file: .cursor/skills/commit-and-pr-hygiene/SKILL.md)
- commodity-news-linking: Repository skill. (file: .cursor/skills/commodity-news-linking/SKILL.md)
- composition-contracts: Repository skill. (file: .cursor/skills/composition-contracts/SKILL.md)
- computer-vision-expert: Repository skill. (file: .cursor/skills/computer-vision-expert/SKILL.md)
- contract-first-graphql: Repository skill. (file: .cursor/skills/contract-first-graphql/SKILL.md)
- data-lineage: Repository skill. (file: .cursor/skills/data-lineage/SKILL.md)
- data-quality-gates: Repository skill. (file: .cursor/skills/data-quality-gates/SKILL.md)
- dependency-and-license-audit: Repository skill. (file: .cursor/skills/dependency-and-license-audit/SKILL.md)
- docs-sync: Repository skill. (file: .cursor/skills/docs-sync/SKILL.md)
- event-contracts: Repository skill. (file: .cursor/skills/event-contracts/SKILL.md)
- frontend-behavior-check: Repository skill. (file: .cursor/skills/frontend-behavior-check/SKILL.md)
- gis-data-layer-react-query: Repository skill. (file: .cursor/skills/gis-data-layer-react-query/SKILL.md)
- golden-tests-and-fixtures: Repository skill. (file: .cursor/skills/golden-tests-and-fixtures/SKILL.md)
- incident-runbook: Repository skill. (file: .cursor/skills/incident-runbook/SKILL.md)
- index-vector: Repository skill. (file: .cursor/skills/index-vector/SKILL.md)
- ingest-postgres: Repository skill. (file: .cursor/skills/ingest-postgres/SKILL.md)
- integration-connector: Repository skill. (file: .cursor/skills/integration-connector/SKILL.md)
- intraday-futures-trading-advisor: Repository skill. (file: .cursor/skills/intraday-futures-trading-advisor/SKILL.md)
- layer-diagnostics-debug: Repository skill. (file: .cursor/skills/layer-diagnostics-debug/SKILL.md)
- minute-candle-performance: Repository skill. (file: .cursor/skills/minute-candle-performance/SKILL.md)
- ml-backtest-hpo-lab: Repository skill. (file: .cursor/skills/ml-backtest-hpo-lab/SKILL.md)
- module-scaffold: Repository skill. (file: .cursor/skills/module-scaffold/SKILL.md)
- moex-instruments-costs: Repository skill. (file: .cursor/skills/moex-instruments-costs/SKILL.md)
- neo4j-migrations-and-constraints: Repository skill. (file: .cursor/skills/neo4j-migrations-and-constraints/SKILL.md)
- news-geopolitics-filter: Repository skill. (file: .cursor/skills/news-geopolitics-filter/SKILL.md)
- news-impact-backtest-lab: Repository skill. (file: .cursor/skills/news-impact-backtest-lab/SKILL.md)
- observability-slo: Repository skill. (file: .cursor/skills/observability-slo/SKILL.md)
- openai-ocr-cost-and-reliability-guardrails: Repository skill. (file: .cursor/skills/openai-ocr-cost-and-reliability-guardrails/SKILL.md)
- parallel-worktree-flow: Repository skill. (file: .cursor/skills/parallel-worktree-flow/SKILL.md)
- patch-series-splitter: Repository skill. (file: .cursor/skills/patch-series-splitter/SKILL.md)
- preferences-presets-migrations: Repository skill. (file: .cursor/skills/preferences-presets-migrations/SKILL.md)
- product-owner: Repository skill. (file: .cursor/skills/product-owner/SKILL.md)
- qa-test-engineer: Repository skill. (file: .cursor/skills/qa-test-engineer/SKILL.md)
- rbac-layer-gating: Repository skill. (file: .cursor/skills/rbac-layer-gating/SKILL.md)
- registry-first: Repository skill. (file: .cursor/skills/registry-first/SKILL.md)
- release-notes: Repository skill. (file: .cursor/skills/release-notes/SKILL.md)
- release-notes-and-changelog: Repository skill. (file: .cursor/skills/release-notes-and-changelog/SKILL.md)
- repeated-issue-review: Repository skill. (file: .cursor/skills/repeated-issue-review/SKILL.md)
- risk-profile-gates: Repository skill. (file: .cursor/skills/risk-profile-gates/SKILL.md)
- schema-migrations-postgres: Repository skill. (file: .cursor/skills/schema-migrations-postgres/SKILL.md)
- secrets-and-config-hardening: Repository skill. (file: .cursor/skills/secrets-and-config-hardening/SKILL.md)
- security-compliance: Repository skill. (file: .cursor/skills/security-compliance/SKILL.md)
- signals-news-bridge-v2: Repository skill. (file: .cursor/skills/signals-news-bridge-v2/SKILL.md)
- skill-creator: Repository skill. (file: .cursor/skills/skill-creator/SKILL.md)
- skill-installer: Repository skill. (file: .cursor/skills/skill-installer/SKILL.md)
- source-onboarding: Repository skill. (file: .cursor/skills/source-onboarding/SKILL.md)
- spread-arbitrage: Repository skill. (file: .cursor/skills/spread-arbitrage/SKILL.md)
- testing-suite: Repository skill. (file: .cursor/skills/testing-suite/SKILL.md)
- trading-ui-dashboard: Repository skill. (file: .cursor/skills/trading-ui-dashboard/SKILL.md)
- tz-oss-scout: Repository skill. (file: .cursor/skills/tz-oss-scout/SKILL.md)
- ui-decision-log: Repository skill. (file: .cursor/skills/ui-decision-log/SKILL.md)
- update-neo4j: Repository skill. (file: .cursor/skills/update-neo4j/SKILL.md)
- validate-crosslayer: Repository skill. (file: .cursor/skills/validate-crosslayer/SKILL.md)
### Flow Order (mandatory)
- Start: `parallel-worktree-flow`.
- UI: `trading-ui-dashboard` -> `ui-decision-log` -> `frontend-behavior-check`.
- Strategy: `intraday-futures-trading-advisor` -> `moex-instruments-costs` -> `risk-profile-gates`.
  - Add `news-geopolitics-filter` for event-risk gating.
  - Add `spread-arbitrage` for pair-spread logic.
- News/signal: `commodity-news-linking` -> `news-impact-backtest-lab` -> `signals-news-bridge-v2`.
- Research/performance: `ml-backtest-hpo-lab`; add `minute-candle-performance` for high-load paths.
- Recheck and pre-push: rerun active verification skills and required checks from `docs/DEV_WORKFLOW.md`.
  - dependency or abstraction changes must include ADR updates under `docs/architecture/adr/`.

### Skill Usage Rules
- If user names a skill (or task clearly matches), use that skill in the same turn.
- Do not carry skills across turns unless re-mentioned.
- Use local `.cursor/skills` as the primary catalog for this repository (including mirrored global skills).
- When global skill content changes, mirror updates via `docs/workflows/skill-governance-sync.md` and re-run `python scripts/validate_skills.py`.
- Before modifying skills, run intent routing:
  - `python scripts/skill_update_decision.py --from-git --request "intent"` to choose between `UPDATE_EXISTING` and `ADD_NEW`.
- When committing skill-related edits, pre-commit guard runs `python scripts/skill_precommit_gate.py` and fails `NO_CHANGE` decisions.
  - Use `SKILL_UPDATE_INTENT="<intent>" git commit ...` for explicit routing.
  - Use `SKILL_DECISION_GATE=0` to bypass during emergency local commits.
- Read skills with progressive disclosure:
  1) open `SKILL.md`;
  2) load only required references;
  3) prefer existing scripts/templates over manual duplication.
- Keep context budget tight: avoid bulk file dumps and deep reference chasing.

## First-Time-Right Protocol (mandatory)
- Applies to research and user-facing business logic.
- Run `docs/checklists/first-time-right-gate.md` before implementation and before pre-push.
- Required report block:
  1) Confirmed coverage.
  2) Missing or risky scenarios.
  3) Resource/time risks and controls.
  4) Highest-priority fixes or follow-ups.

## Task Request Contract (mandatory)
- Before non-trivial implementation, fill `docs/session_handoff.md`:
  - `## Task Request Contract` with objective, scope, out-of-scope, constraints, done evidence, priority rule.
  - `## First-Time-Right Report` with all 4 required report lines.
  - `## Repetition Control` with max same-path attempts, stop trigger, reset action, new search space, next probe.
- Validate with:
  - `python scripts/validate_task_request_contract.py`
- If request is vague or contradictory, stop and ask for clarification; do not continue with implicit assumptions.

## Worktree Safety Protocol (mandatory)
- Before any code edits or long-running commands, run:
  - `./scripts/worktree_guard.ps1 -Action Check`
- If context is missing, initialize:
  - `./scripts/worktree_guard.ps1 -Action Init -WorktreePath "<path>" -Branch "<branch>" -ContextTtlHours 12`
- If `Check` reports mismatch, stop and switch to expected worktree/branch.
- If context expired, re-run `Init` before development actions.
- Use `./scripts/worktree_guard.ps1 -Action Show` when reporting active context.
</INSTRUCTIONS>
