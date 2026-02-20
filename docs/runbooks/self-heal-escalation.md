# Self-Heal Escalation Runbook

## Scope
Escalation path for failed deterministic self-heal runs.

## Trigger
- `scripts/self_heal.py` ends with `final_pass=false`.
- Workflow `.github/workflows/self-heal.yml` fails after remediation attempts.

## Immediate Actions
1. Inspect `self-heal-report.json` artifact.
2. Identify failing gate command(s).
3. Reproduce locally with:
   - `python scripts/run_lean_gate.py --skip-metrics`
   - `python scripts/validate_quality_scorecards.py`

## Escalation Contract
When self-heal fails, create an issue with:
- failing command(s),
- first observed timestamp,
- last known passing commit,
- recommended owner lane (`governance`, `architecture`, `quality`, `frontend`, `backend`),
- mitigation proposal.

## Ownership
- Primary: engineering-platform
- Secondary: architecture-owner (for boundary/policy failures)
- Secondary: quality-engineering (for scorecard/test failures)

## Exit Criteria
- Failing gate passes on default branch.
- Root cause and mitigation are documented in:
  - `memory/agent_memory.yaml` (incident + remediation),
  - `plans/PLANS.yaml` (follow-up item if needed).
