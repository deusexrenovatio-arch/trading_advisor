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
| Session handoff context budget contract | `python scripts/validate_session_handoff.py` | Engineering owner | `governance` |
| Operator request contract and first-time-right report completeness | `python scripts/validate_task_request_contract.py` | Engineering owner | `governance` |
| Task outcome closeout and ledger completeness | `python scripts/validate_task_outcomes.py` | Engineering owner | `governance`, `quality-scorecards` |
| Rolling process-regression thresholds after burn-in | `python scripts/validate_process_regressions.py` | Engineering enablement | `quality-scorecards` |
| Recurring-error prevention with behavior-change evidence and loop-breaker control | `python scripts/validate_agent_memory.py` + `python scripts/validate_task_request_contract.py` | Engineering owner | `governance` |
| Contract-first API surface | `python scripts/validate_api_v2_contract_parity.py` | Backend platform | `governance` |
| Directional module boundaries (no core -> UI imports) | `python scripts/validate_import_boundaries.py` | Architecture owner | `governance` |
| Hard architecture policy-as-code | `python scripts/validate_architecture_policy.py` | Architecture owner | `governance` |
| Progressive disclosure + short feedback loops | `python scripts/task_session.py begin --request "<request>"` + `python scripts/run_loop_gate.py --from-git --git-ref HEAD` | Engineering owner | `governance` |
| Context budget and concise handoff contract | `python scripts/validate_session_handoff.py` | Engineering owner | `governance` |
| PR-only merge discipline for `main` | `python scripts/validate_pr_only_policy.py` | Engineering manager | `governance` |
| Scenario traceability to executable/acceptance cases | `python scripts/validate_test_cases.py` | QA owner | `governance` |
| User-needs coverage linked to acceptance scenarios | `python scripts/validate_user_needs_catalog.py` | Product owner | `governance` |
| Skill/workflow compliance as pre-implementation guardrail | `python scripts/validate_skills.py` | Engineering manager | `governance` |
| Deterministic second-pass review | `python scripts/agent_review.py` | QA owner | `agent-review` |
| Scheduled documentation entropy control | `python scripts/doc_gardening_report.py` | Engineering enablement | `docs-gardening` |
| Quality scorecards with blocking thresholds | `python scripts/validate_quality_scorecards.py` | Architecture + QA | `quality-scorecards` |
| Dependency/abstraction ADR governance | `python scripts/validate_dependency_decisions.py` | Architecture owner | `governance` |
| CODEOWNERS ownership routing contract | `python scripts/validate_codeowners.py` | Engineering manager | `governance`, `quality-scorecards` |
| Enforceable engineering taste invariants | `python scripts/validate_taste_invariants.py` | Engineering owner | `governance`, `quality-scorecards` |
| Python style/lint gate | `python scripts/validate_python_style.py` | Engineering owner | `governance`, `quality-scorecards` |
| Structured API logging schema contract | `python scripts/validate_structured_logging.py` | Backend + observability owners | `governance`, `quality-scorecards` |
| Flaky-test governance policy | `python scripts/validate_flaky_policy.py` | Quality engineering | `governance`, `quality-scorecards` |
| Local observability stack contract | `python scripts/validate_observability_stack.py` | Platform observability | `governance`, `quality-scorecards` |
| Actionable remediation guidance contract | `python scripts/validate_governance_remediation.py` | Engineering enablement | `governance` |
| Combined governance dashboard artifact | `python scripts/build_governance_dashboard.py` | Engineering enablement | `governance-dashboard` |
| Autonomous self-heal loop | `python scripts/self_heal.py` | Engineering platform | `self-heal` |
| Self-heal escalation to human judgment | `docs/runbooks/self-heal-escalation.md` + workflow escalation step | Engineering platform | `self-heal` |
| Agent operational memory integrity | `python scripts/validate_agent_memory.py` | Engineering owner | `governance` |
| Autonomy KPI observability | `python scripts/autonomy_kpi_report.py` | Engineering enablement | `docs-gardening` |
| Process-improvement telemetry and weekly rollups | `python scripts/process_improvement_report.py` | Engineering enablement | `docs-gardening`, `governance-dashboard` |
| Runtime regression and behavior stability | `pytest` | Backend + Quant owners | `backend`, `perf-minute-runtime` |
| Frontend integration safety | `npm --prefix ui-web run lint` + `npm --prefix ui-web run build` | Frontend owner | `frontend` |
| UI journey verification with artifacts | `npm --prefix ui-web run test:e2e` | Frontend owner | `frontend-e2e` |

## Baseline Metrics
| Metric | Definition | Source |
| --- | --- | --- |
| `spec_drift_count` | Count of API operations mismatched between Flask `/api/v2/*` routes and `docs/contracts/api-v2.yaml` | `scripts/harness_baseline_metrics.py` |
| `boundary_violations` | Count of forbidden imports from core modules into `moex_carry.ui.*` (allowlist excluded) | `scripts/harness_baseline_metrics.py` |
| `manual_scenarios_count` | Count of scenarios with `type: manual` in acceptance catalog | `scripts/harness_baseline_metrics.py` |
| `unlinked_test_cases_count` | Count of active (non-planned) `TC-*` definitions not linked from acceptance scenarios | `scripts/harness_baseline_metrics.py` |
| `planned_unlinked_test_cases_count` | Count of planned (`## Planned ...`) `TC-*` cases not linked yet (non-blocking) | `scripts/validate_test_cases.py` output |

## Autonomy KPIs
| KPI | Definition | Source |
| --- | --- | --- |
| `autonomous_completion_rate` | Share of completed plan items with `execution_mode=autonomous` | `scripts/autonomy_kpi_report.py` |
| `mean_cycle_time_days` | Mean cycle time for completed plan items with start/end dates | `scripts/autonomy_kpi_report.py` |
| `memory_decisions_count` | Number of decision records in agent memory | `scripts/autonomy_kpi_report.py` |
| `self_heal_workflow_enabled` | Binary indicator that self-heal CI loop is configured | `scripts/autonomy_kpi_report.py` |
| `process_correct_first_time_pct` | Share of recent completed tasks closed as `correct_first_time` | `scripts/autonomy_kpi_report.py` |
| `process_repeat_error_rate` | Share of recent completed tasks that repeated an existing incident signature | `scripts/autonomy_kpi_report.py` |

## Sprint 0 Exit Gate
- Document exists and contains `Principle -> Check -> Owner -> CI Job` mapping.
- Baseline metrics are computed in CI on every PR/push.
- Metrics are published into GitHub Actions summary (`GITHUB_STEP_SUMMARY`).
