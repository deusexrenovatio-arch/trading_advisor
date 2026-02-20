# Documentation Index

This directory is the repository knowledge system for agent-first engineering.

## Source of Truth
- `AGENTS.md`
- `harness-guideline.md`
- `docs/DEV_WORKFLOW.md`
- `docs/session_handoff.md`
- `plans/PLANS.yaml`
- `memory/agent_memory.yaml`
- `CODEOWNERS`

## Architecture
- `docs/architecture/trading-advisor.md`
- `docs/architecture/layers-v2.md`
- `docs/architecture/entities-v2.md`
- `docs/architecture/architecture-map-v2.md`
- `docs/architecture/modules/`

## Contracts
- `docs/contracts/api-v2.yaml`
- `contracts/decision-log.schema.json`
- `contracts/decision-view.schema.json`

## Governance and Process
- `agent-runbook.md`
- `docs/checklists/first-time-right-gate.md`
- `docs/planning/plans-registry.md`
- `docs/workflows/context-budget.md`
- `docs/workflows/worktree-governance.md`
- `docs/runbooks/governance-remediation.md`
- `docs/runbooks/self-heal-escalation.md`
- `docs/runbooks/flaky-tests-policy.md`

## Validation Commands
- `python scripts/run_lean_gate.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/validate_pr_only_policy.py`
- `python scripts/validate_quality_scorecards.py`
- `python scripts/validate_python_style.py`
- `python scripts/validate_structured_logging.py`
- `python scripts/validate_codeowners.py`
- `python scripts/build_governance_dashboard.py`
- `pytest tests/architecture -q`
- `pytest tests/perf -q`
- `npm --prefix ui-web run lint`
- `npm --prefix ui-web run build`

## Update Rule
When adding a new first-class document domain, update this index in the same change.
