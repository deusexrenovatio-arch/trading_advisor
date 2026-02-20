## Summary
- 

## Why
- 

## Impact
- Modules:
- Contracts / schemas:
- Data / migrations:

## Risks & rollback
- 

## Verification
- [ ] `pytest`
- [ ] `npm run lint`
- [ ] `npm run build`
- [ ] `npm run test:e2e`
- [ ] `python scripts/validate_quality_scorecards.py`
- [ ] `python scripts/validate_python_style.py`
- [ ] `python scripts/validate_structured_logging.py`
- [ ] `python scripts/validate_codeowners.py`
- [ ] `python scripts/acceptance_check.py` (optional)

## Checklist
- [ ] `plans/PLANS.yaml` updated for status/acceptance changes (if applicable)
- [ ] `memory/agent_memory.yaml` updated for durable decisions/incidents/patterns (if applicable)
- [ ] ADR updated in `docs/architecture/adr/` for dependency/abstraction changes (if applicable)
- [ ] Flaky policy impact reviewed (`configs/flaky_policy.yaml`) if retries/quarantine touched
- [ ] `CODEOWNERS` updated when ownership lanes changed (if applicable)
- [ ] Registry updated (if needed)
- [ ] Contracts updated (if needed)
- [ ] Tests added/updated
- [ ] Docs updated (if needed)
- [ ] Observability updated (if needed)
- [ ] Release notes fragment added in `docs/releases.d/`
