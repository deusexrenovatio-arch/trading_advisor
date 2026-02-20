# Harness Engineering Alignment Report

Date: 2026-02-20  
Repo: `d:\New Project`  
Audit mode: read-only (no code changes, no PR actions)

## Executive summary
- Repository strongly aligns with Harness/agent-first fundamentals: explicit source-of-truth files, machine-checked governance, and deterministic CI loops are present.
- Operating model is documented as intent/acceptance-first and enforced by process checklists plus machine-readable user-needs/acceptance mappings.
- Architecture legibility and boundary enforcement are mature: layered architecture docs, policy-as-code, structural checks, and architecture smoke tests are in place.
- Entropy management is above baseline: scheduled docs-gardening, daily self-heal with auto-PR, and autonomy KPI reporting are implemented.
- Main gaps are throughput/UX of enforcement: no explicit flaky-test policy, no CODEOWNERS routing, and no Playwright e2e execution/artifact capture in CI.
- Observability/NFR automation is good for backend runtime/perf but still partial for end-to-end journey budgets and full local tracing stack.
- GitHub branch protection/required-check settings could not be verified from repo context (403 from API), so org-level enforcement remains partially unknown.

## Scorecard

| ID | Status | Evidence |
| --- | --- | --- |
| HE-01 | PASS | `AGENTS.md:4`, `docs/checklists/first-time-right-gate.md:12`, `configs/user_needs_catalog.yaml` |
| HE-02 | PARTIAL | `memory/agent_memory.yaml:16`, `docs/checklists/first-time-right-gate.md:49`, `scripts/self_heal.py` |
| HE-03 | PASS | `AGENTS.md:55`, `docs/DEV_WORKFLOW.md:73`, `scripts/run_lean_gate.py:34` |
| HE-04 | PASS | `AGENTS.md:5`, `AGENTS.md:8` |
| HE-05 | PARTIAL | Structured docs tree exists (`docs/*`), but missing global docs index: `docs/README.md` absent |
| HE-06 | PASS | `plans/PLANS.yaml`, `docs/planning/plans-registry.md:3`, `memory/agent_memory.yaml` |
| HE-07 | PASS | `scripts/validate_harness_guideline.py`, `scripts/doc_gardening_report.py:13`, `.github/workflows/docs-gardening.yml:4` |
| HE-08 | PASS | `harness-guideline.md`, `docs/architecture/trading-advisor.md`, `docs/contracts/api-v2.yaml` |
| HE-09 | PARTIAL | `docs/architecture/modules/compute-stack-policy.md:18`, `configs/architecture_policy.yaml`; no ADR-style dependency record |
| HE-10 | PASS | `docs/architecture/layers-v2.md:6`, `docs/architecture/trading-advisor.md:32`, `docs/architecture/architecture-map-v2.md:5` |
| HE-11 | PASS | `configs/architecture_policy.yaml:2`, `scripts/validate_import_boundaries.py:86`, `tests/architecture/test_governance_policies.py` |
| HE-12 | PARTIAL | Enforced: quality scorecards + commitlint + eslint (`configs/quality_scorecards.yaml`, `commitlint.config.cjs`, `ui-web/eslint.config.js`); missing enforced Python style/file-size/log schema invariants |
| HE-13 | PARTIAL | Good remediation examples (`scripts/worktree_guard.ps1:145`, `.github/workflows/ci.yml:210`), but many validators return failures without explicit fix steps |
| HE-14 | PASS | `docs/workflows/worktree-governance.md`, `scripts/worktree_guard.ps1`, `docs/DEV_WORKFLOW.md:8` |
| HE-15 | PARTIAL | Playwright exists (`ui-web/package.json:11`, `ui-web/playwright.config.ts:11`), but CI does not run e2e (`NO_E2E_IN_CI`) |
| HE-16 | PARTIAL | Runtime observability endpoints and runbook exist (`src/moex_carry/ui/app.py:3257`, `docs/runbooks/ops-slo-alerts.md`), but local observability stack is minimal (`docker-compose.yml` only postgres) |
| HE-17 | PARTIAL | Automated perf/NFR checks exist (`tests/perf/*`, `.github/workflows/ci.yml:135`), but startup/journey budgets are not uniformly automated |
| HE-18 | PARTIAL | Strong gates exist (`.githooks/pre-push`, CI jobs), but no explicit flaky management policy; branch protection required-checks not verifiable from repo |
| HE-19 | PASS | Deterministic agent review is integrated in CI (`.github/workflows/ci.yml:12`, `scripts/agent_review.py`) |
| HE-20 | PARTIAL | Recovery loop exists (`scripts/self_heal.py`, `.github/workflows/self-heal.yml`), but full autonomous incident triage/escalation workflow is not end-to-end formalized |
| HE-21 | PASS | Golden principles + scheduled entropy controls exist (`harness-guideline.md`, `.github/workflows/docs-gardening.yml`, `.github/workflows/self-heal.yml`) |

## Detailed findings

### A. Operating model

What found:
- Harness-oriented intent and routing model are explicit, including source-of-truth files and non-negotiable execution loop (`AGENTS.md:4`, `AGENTS.md:8`, `AGENTS.md:16`).
- Intent/acceptance discipline is formalized with first-time-right gates (`docs/checklists/first-time-right-gate.md:12`, `docs/checklists/first-time-right-gate.md:18`).
- User needs and acceptance mappings are machine-readable (`configs/user_needs_catalog.yaml`, `configs/acceptance_scenarios.yaml`) and validated (`scripts/validate_user_needs_catalog.py`).

Why important:
- Enables "humans define intent + AC; agents execute" with less prompt fragility.

Evidence:
- `AGENTS.md:5` states file is a routing map, not monolithic manual.
- `docs/DEV_WORKFLOW.md:73` defines lean loop with machine checks.
- `memory/agent_memory.yaml:16` records incident -> remediation through new guardrails.

### B. Repo as system of record

What found:
- Execution plans are first-class and versioned (`plans/PLANS.yaml`), with schema and invariants (`docs/planning/plans-registry.md`).
- Decision/incidents/pattern memory is versioned (`memory/agent_memory.yaml`) and validated (`scripts/validate_agent_memory.py`).
- Documentation governance is automated by scheduled docs-gardening (`.github/workflows/docs-gardening.yml`).

Why important:
- Keeps operational knowledge durable and auditable in git.

Evidence:
- `plans/PLANS.yaml:1` and multiple autonomous governance items.
- `scripts/doc_gardening_report.py:13` required docs list includes plans and memory.
- Gap: `docs/README.md` missing (`MISSING docs/README.md`), reducing discoverability at root docs level.

### C. Agent legibility

What found:
- Architecture, contracts, workflows, and operations are documented in-repo (`docs/architecture/*`, `docs/contracts/*`, `docs/runbooks/*`).
- Compute stack and abstraction choices are intentionally documented for high-load legibility (`docs/architecture/modules/compute-stack-policy.md:6`, `docs/architecture/modules/compute-stack-policy.md:18`).

Why important:
- Agents need deterministic, local context to plan/refactor safely.

Evidence:
- `docs/architecture/architecture-map-v2.md:5` marks JSON map as source of truth.
- `scripts/sync_architecture_map.py:170` emits explicit remediation when map is out of sync.
- Partial gap: no ADR-like mandatory dependency rationale workflow for every new dependency.

### D. Architecture & taste enforcement

What found:
- Explicit architecture model and boundaries exist (`docs/architecture/layers-v2.md`, `docs/architecture/trading-advisor.md`).
- Architecture policy-as-code is active and blocking (`configs/architecture_policy.yaml:2`, `.github/workflows/ci.yml:45` + governance).
- Quality scorecards introduce enforceable dimensions (reliability/security/frontend/design/product-sense).

Why important:
- Converts architecture/taste from "guidance" into machine-enforced constraints.

Evidence:
- `scripts/validate_import_boundaries.py:72` prints boundary violations.
- `tests/architecture/test_governance_policies.py` runs smoke checks for plans/policy/memory/scorecards.
- `configs/quality_scorecards.yaml` with `threshold: 1.0` for each dimension.
- Partial gap: no enforced Python style/lint tool (e.g., ruff/flake8), no file-size/log-schema hard gates.

### E. App legibility & feedback loops

What found:
- Isolated worktree flow is codified and guarded (`docs/workflows/worktree-governance.md`, `scripts/worktree_guard.ps1`).
- Playwright e2e assets exist and include trace on retry (`ui-web/playwright.config.ts:11`).
- Backend observability endpoints and in-memory metrics exist (`src/moex_carry/ui/app.py:3257`, `src/moex_carry/ui/app.py:3294`, `src/moex_carry/observability/runtime_metrics.py`).
- Perf thresholds are testable and CI-backed (`tests/perf/*`, `.github/workflows/ci.yml:150`).

Why important:
- Agents need fast local reproduction, visible runtime signals, and automated NFR feedback.

Evidence:
- `ui-web/package.json:11` defines `test:e2e`.
- CI currently does not execute e2e (`NO_E2E_IN_CI`).
- `docker-compose.yml` only provisions postgres; no full local observability stack (traces/log pipeline).

### F. Merge/review for throughput

What found:
- PR template and pre-push gates are strong (`.github/pull_request_template.md`, `.githooks/pre-push`).
- Agent-to-agent deterministic review exists (`.github/workflows/ci.yml:12`, `scripts/agent_review.py`).
- Dependency audit is explicitly non-blocking (`.github/workflows/ci.yml:109` `continue-on-error: true`).

Why important:
- Throughput requires balancing gate strictness with operational resilience.

Evidence:
- Missing ownership routing files (`MISSING .github/CODEOWNERS`, `MISSING CODEOWNERS`).
- No explicit flaky quarantine/retry policy was found (`rg flaky|quarantine` only incidental mentions).
- Unknown external enforcement:
  - command: `gh api repos/deusexrenovatio-arch/trading_advisor/branches/main/protection`
  - output: `403 Upgrade to GitHub Pro or make this repository public...`

### G. Autonomy & recovery

What found:
- Deterministic self-heal loop exists with remediation actions and auto-PR creation (`scripts/self_heal.py`, `.github/workflows/self-heal.yml:40`).
- Lean gate and scorecards provide closed validation loop before/after changes (`scripts/run_lean_gate.py`, `scripts/validate_quality_scorecards.py`).

Why important:
- True agent-first systems need recovery paths before human escalation.

Evidence:
- `scripts/self_heal.py` records `initial_pass`, `final_pass`, `autofix_applied`.
- `.github/workflows/self-heal.yml:42` uses `create-pull-request`.
- Partial gap: no explicit "escalate-to-human judgment" runbook for failed self-heal beyond generic failure.

### H. Entropy / garbage collection

What found:
- Golden principles and checks are centralized (`harness-guideline.md`).
- Entropy checks run on schedule (`docs-gardening` weekly, `self-heal` daily).
- Docs/report freshness and stale-plan detection are automated (`scripts/doc_gardening_report.py:103`).

Why important:
- Continuous cleanup prevents drift and keeps agent context reliable.

Evidence:
- `.github/workflows/docs-gardening.yml:4`, `.github/workflows/self-heal.yml:4`.
- `scripts/doc_gardening_report.py` counts TODOs and flags stale plans.

## Verification commands (read-only evidence)

```bash
python scripts/run_lean_gate.py --skip-metrics
# lean gate: OK; includes plans/memory/harness/policy/test-cases/user-needs/skills checks

python scripts/validate_quality_scorecards.py
# quality scorecards: OK

pytest tests/architecture -q
# 6 passed in ~0.75s

gh api repos/deusexrenovatio-arch/trading_advisor/branches/main/protection
# HTTP 403 (cannot verify branch protection via current access/repo plan)
```

## Recommendations (Top-10 by Impact/Cost)

| # | Action | Impact | Cost | Priority |
| --- | --- | --- | --- | --- |
| 1 | Add CI Playwright smoke job (`npm run test:e2e`) + upload trace/video artifacts | High | Medium | P0 |
| 2 | Add explicit flaky-test policy (quarantine, retry budget, owner, exit SLA) in `docs/DEV_WORKFLOW.md` | High | Low | P0 |
| 3 | Add `CODEOWNERS` and owner routing for governance/architecture/contracts | High | Low | P0 |
| 4 | Add `docs/README.md` as global docs index (source-of-truth map + update flow) | Medium | Low | P1 |
| 5 | Introduce Python style gate (`ruff`/`ruff format` or equivalent) in CI/pre-push | Medium | Medium | P1 |
| 6 | Add structured logging schema checks (JSON fields/invariants) for critical API paths | Medium | Medium | P1 |
| 7 | Add automated startup/journey NFR budgets (API cold start, key UI journey latency) | High | Medium | P1 |
| 8 | Formalize escalation runbook for failed self-heal and repeated auto-fix failures | Medium | Low | P1 |
| 9 | Add ADR template + lightweight validation for new dependency/abstraction decisions | Medium | Medium | P2 |
| 10 | Publish one combined CI "governance dashboard" artifact (scorecards + KPI + entropy + findings) | Medium | Low | P2 |

### Quick wins (fast)
- Add `docs/README.md` index and link from root `README.md`.
- Add `CODEOWNERS` for `scripts/`, `docs/`, `configs/`, `src/`.
- Add explicit flaky policy section in `docs/DEV_WORKFLOW.md`.
- Add CI step to run at least one Playwright smoke spec and upload artifacts.

## Missing capabilities backlog

1. Ownership routing capability
- Missing: `CODEOWNERS`.
- Add: deterministic reviewer assignment by area.

2. Flaky management capability
- Missing: formal flaky taxonomy/quarantine policy.
- Add: CI retry/quarantine lanes + follow-up SLA tracking.

3. E2E artifact loop capability
- Missing: Playwright in CI with screenshot/video/trace artifacts.
- Add: e2e workflow + artifact upload + PR summary links.

4. Python taste enforcement capability
- Missing: repository-wide Python lint/format gate.
- Add: `ruff` (or equivalent) in CI + pre-push.

5. Structured logging enforceability
- Missing: machine-checked log field schema/invariants.
- Add: log contract tests for key endpoints and workers.

6. Journey-level NFR automation
- Missing: automated budgets for startup and operator journeys.
- Add: dedicated performance journey tests (API+UI).

7. Docs discoverability capability
- Missing: top-level docs index (`docs/README.md`).
- Add: curated map of authoritative docs and update obligations.

8. External governance verification capability
- Missing in-repo proof of GitHub required-check/branch-protection settings.
- Add: periodic external audit checklist + captured evidence snapshot.

## Unknown / manual verification required

1. Branch protection and required checks enforcement (GitHub settings)
- Status: UNKNOWN from repo-only audit.
- Why: API call returned 403 for protection endpoint.
- Manual check:
  - GitHub UI: `Settings -> Branches -> Branch protection rules`.
  - Confirm required checks include `governance`, `quality-scorecards`, `backend`, `frontend`, `agent-review`.

2. Real-world flaky frequency and override behavior
- Status: UNKNOWN from static repo scan.
- Why: requires CI run history and failure trend data.
- Manual check:
  - Inspect last 30 CI runs by job and failure reason.
  - Measure retry/pass-on-rerun ratios per test suite.
