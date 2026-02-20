# Harness Guideline Baseline

## Scope
This document defines the repository baseline aligned to Harness Engineering principles:
- explicit contracts,
- strict dependency boundaries,
- deterministic governance checks,
- measurable quality signals.

## Principle Mapping
| Principle | Check | Owner | CI Job |
| --- | --- | --- | --- |
| Machine-readable execution plan | `python scripts/validate_plans.py` | Engineering owner | `governance` |
| Contract-first API surface | `python scripts/validate_api_v2_contract_parity.py` | Backend platform | `governance` |
| Directional module boundaries (no core -> UI imports) | `python scripts/validate_import_boundaries.py` | Architecture owner | `governance` |
| Hard architecture policy-as-code | `python scripts/validate_architecture_policy.py` | Architecture owner | `governance` |
| Progressive disclosure + short feedback loops | `python scripts/run_lean_gate.py` | Engineering owner | `governance` |
| Scenario traceability to executable/acceptance cases | `python scripts/validate_test_cases.py` | QA owner | `governance` |
| User-needs coverage linked to acceptance scenarios | `python scripts/validate_user_needs_catalog.py` | Product owner | `governance` |
| Skill/workflow compliance as pre-implementation guardrail | `python scripts/validate_skills.py` | Engineering manager | `governance` |
| Deterministic second-pass review | `python scripts/agent_review.py` | QA owner | `agent-review` |
| Scheduled documentation entropy control | `python scripts/doc_gardening_report.py` | Engineering enablement | `docs-gardening` |
| Runtime regression and behavior stability | `pytest` | Backend + Quant owners | `backend`, `perf-minute-runtime` |
| Frontend integration safety | `npm --prefix ui-web run lint` + `npm --prefix ui-web run build` | Frontend owner | `frontend` |

## Baseline Metrics
| Metric | Definition | Source |
| --- | --- | --- |
| `spec_drift_count` | Count of API operations mismatched between Flask `/api/v2/*` routes and `docs/contracts/api-v2.yaml` | `scripts/harness_baseline_metrics.py` |
| `boundary_violations` | Count of forbidden imports from core modules into `moex_carry.ui.*` (allowlist excluded) | `scripts/harness_baseline_metrics.py` |
| `manual_scenarios_count` | Count of scenarios with `type: manual` in acceptance catalog | `scripts/harness_baseline_metrics.py` |
| `unlinked_test_cases_count` | Count of active (non-planned) `TC-*` definitions not linked from acceptance scenarios | `scripts/harness_baseline_metrics.py` |

## Sprint 0 Exit Gate
- Document exists and contains `Principle -> Check -> Owner -> CI Job` mapping.
- Baseline metrics are computed in CI on every PR/push.
- Metrics are published into GitHub Actions summary (`GITHUB_STEP_SUMMARY`).
