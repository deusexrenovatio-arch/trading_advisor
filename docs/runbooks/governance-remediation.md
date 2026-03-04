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
- For incidents on/after `incident.enforce_learning_fields_from` in `configs/agent_incident_policy.yaml`, also set:
  - `incident_signature`
  - `prevention_change`
  - `prevention_artifact`
  - `prevention_check`
  - `loop_breaker_trigger`
  - `search_space_reset`
  - `same_path_attempts` (must be positive integer and within policy max).

## `python scripts/validate_session_handoff.py`
- Keep `docs/session_handoff.md` present and updated for the current stream.
- Ensure required sections exist: Goal, Current Delta, Blockers, Next Step, Validation.
- Keep `Current Delta` concise (maximum 8 bullets) and avoid pasting large instruction blocks.
- For policy details, follow `docs/workflows/context-budget.md`.

## `python scripts/validate_task_request_contract.py`
- Keep `## Task Request Contract` in `docs/session_handoff.md` with:
  - Objective
  - In Scope
  - Out of Scope
  - Constraints
  - Done Evidence
  - Priority Rule
- Keep `## First-Time-Right Report` in `docs/session_handoff.md` with all four numbered report lines.
- Keep `## Repetition Control` in `docs/session_handoff.md` with:
  - Max Same-Path Attempts
  - Stop Trigger
  - Reset Action
  - New Search Space
  - Next Probe
- Use `docs/checklists/task-request-contract.md` as the canonical template.

## `python scripts/validate_pr_only_policy.py`
- Keep `.githooks/pre-push` in PR-only mode for `main`.
- Keep `AGENTS.md`, `docs/DEV_WORKFLOW.md`, and `README.md` aligned with the same policy text.
- Legacy `MOEX_CARRY_ALLOW_MAIN_PUSH` override examples must be removed from policy docs.
- Emergency direct push is allowed only with both:
  - `MOEX_CARRY_EMERGENCY_MAIN_PUSH=1`
  - `MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON='<ticket/incident>'`

## `python scripts/validate_dependency_decisions.py`
- If dependency manifests changed, add/update an ADR in `docs/architecture/adr/`.
- Use naming pattern `NNNN-short-kebab-title.md`.

## `python scripts/validate_taste_invariants.py`
- Keep file sizes within hard limits from `configs/taste_invariants.yaml` (`max_lines_default` + `allowed_large_files`).
- Treat `target_lines_default` + `target_large_files` as non-blocking decomposition targets and ratchet them down after each split.
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
