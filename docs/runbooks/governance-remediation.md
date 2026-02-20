# Governance Remediation Guide

Use this guide when a governance gate fails.

## `python scripts/run_lean_gate.py`
- Read the first failing command from output.
- Run that command directly to isolate details.
- Apply the matching remediation section below.

## `python scripts/validate_plans.py`
- Ensure `plans/PLANS.yaml` follows schema in `docs/planning/plans-registry.md`.
- Fix invalid statuses, missing `execution_mode`, and unknown dependencies.

## `python scripts/validate_agent_memory.py`
- Ensure `memory/agent_memory.yaml` has valid ISO dates and unique IDs.
- For incidents, set `remediation_type` to one of:
  - `capability`
  - `guardrail`
  - `docs`
  - `test`
  - `workflow`

## `python scripts/validate_session_handoff.py`
- Keep `docs/session_handoff.md` present and updated for the current stream.
- Ensure required sections exist: Goal, Current Delta, Blockers, Next Step, Validation.
- Keep `Current Delta` concise (maximum 8 bullets) and avoid pasting large instruction blocks.
- For policy details, follow `docs/workflows/context-budget.md`.

## `python scripts/validate_session_handoff.py`
- Keep `docs/session_handoff.md` compact and up to date for handoff continuity.
- Required sections: Goal, Current Delta, Blockers, Next Step, Validation.
- Keep context budget within validator limits (line/bullet caps).

## `python scripts/validate_dependency_decisions.py`
- If dependency manifests changed, add/update an ADR in `docs/architecture/adr/`.
- Use naming pattern `NNNN-short-kebab-title.md`.

## `python scripts/validate_taste_invariants.py`
- Keep file sizes within configured limits (`configs/taste_invariants.yaml`).
- Avoid wildcard imports and keep module naming conventions.
- Keep structured logging default format intact.

## `python scripts/validate_python_style.py`
- Run `python -m ruff check src tests scripts` and fix reported issues.
- Keep the style gate green before pushing to avoid CI-only failures.

## `python scripts/validate_structured_logging.py`
- Keep `configs/structured_logging_policy.yaml`, `src/moex_carry/logging.py`, and `src/moex_carry/ui/app.py` aligned.
- Ensure `/api/v2/*` responses emit structured JSON logs with required fields.

## `python scripts/validate_codeowners.py`
- Keep `CODEOWNERS` entries aligned with `configs/codeowners_policy.yaml`.
- Ensure required governance and architecture paths have explicit owners.

## `python scripts/validate_flaky_policy.py`
- Ensure `configs/flaky_policy.yaml` has owner, SLA, retry budget, and quarantine limits.
- Align wording with `docs/runbooks/flaky-tests-policy.md`.

## `python scripts/validate_observability_stack.py`
- Keep `docker-compose.observability.yml` and observability docs in sync.
- Ensure required services and ports are defined.

## `python scripts/validate_governance_remediation.py`
- Keep this runbook aligned with active governance commands.
- Add sections for any newly introduced blocking validator.

## `python scripts/validate_quality_scorecards.py`
- Find failing dimension/check in the report.
- Run the failing command directly.
- Fix and rerun until all dimensions meet thresholds.

## `pytest tests/perf -q`
- If runtime budgets fail, inspect thresholds and recent changes in hot paths.
- Preserve correctness; optimize kernels/orchestration before raising budgets.

## `npm --prefix ui-web run test:e2e`
- Reproduce locally with:
  - `cd ui-web`
  - `npx playwright install`
  - `npm run test:e2e`
- Use Playwright trace/report artifacts to locate UI regressions.

## `python scripts/build_governance_dashboard.py`
- Regenerate combined dashboard artifact:
  - `python scripts/build_governance_dashboard.py --output governance-dashboard.md --artifacts-dir .runlogs/governance-dashboard`
- Verify all component reports are produced and referenced in dashboard table.
