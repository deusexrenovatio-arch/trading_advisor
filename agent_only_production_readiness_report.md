# Agent-Only Production Readiness Report

Date: 2026-02-22  
Repo: `d:\New Project`  
Branch: `chore/pr-only-main-hardening` (`be6d237`)  
Mode: Read-mostly audit (no code/config edits; only report artifacts created)

## 1) Executive summary
- Governance and delivery discipline are strong: PR-only flow, CODEOWNERS, deterministic CI gates, quality scorecards, and scheduled self-heal are implemented.
- The project is primarily a self-hosted trading advisor platform (Flask/Dash + TypeScript UI), not a production agent-runtime platform with standardized tool-plane.
- AO-01/AO-03/AO-05 remain major gaps: no MCP/equivalent tool protocol, no dedicated tool gateway/proxy with auth and policy interception, no dynamic tool discovery.
- Security baseline for repo hygiene exists (`scan_secrets`, `.gitignore` for local secrets), but production-grade controls are incomplete: no auth-by-default API layer, no outbound allowlist governance, no DLP.
- Runtime observability exists for API/SLO and structured logs, but full agent trajectory tracing/evaluation is missing.
- Policy enforcement exists for business actions (fail-closed execution checks, idempotency, audit fields), but not as a generic pre-tool-call enforcement plane.
- Release governance is mature (CI, PR template, release-note fragment gate), but rollback/versioning of runtime agent configs and endpoints is only partially formalized.
- Current readiness for production **agent-only** operation is **insufficient** without tool-plane/security/eval hardening.

## 2) Stack & Signals

| Signal found | Meaning | Confidence |
| --- | --- | --- |
| `pyproject.toml:12-23`, `src/moex_carry/ui/app.py:2006` | Python backend (Flask/Dash) + trading-domain logic; not an agent SDK runtime by default | High |
| `ui-web/vite.config.ts:8-15`, `README.md:48` | TS frontend with Vite proxy to backend | High |
| `AGENTS.md:38-74`, `.cursor/skills/*` (14 skills) | Repo-level skill catalog for development workflow orchestration | High |
| `scripts/validate_skills.py:11-139` | Mechanical validation of skill registry consistency with `AGENTS.md` | High |
| `.github/workflows/ci.yml:45-324` | Strong CI governance/quality/release-note gating | High |
| `scripts/run_lean_gate.py:34-72` | Deterministic local/CI governance loop | High |
| `src/moex_carry/logging.py:9-67`, `src/moex_carry/observability/runtime_metrics.py:16-100`, `src/moex_carry/ui/app.py:4706-4859` | API structured logs + in-memory SLO metrics exist | High |
| `rg -n --ignore-case "mcp|model context protocol|tool registry" .` -> no hits | No evidence of MCP/equivalent standardized tool-plane | High |
| `rg -n --ignore-case "flask_login|jwt|oauth|Authorization" src pyproject.toml` -> no hits; `src/moex_carry/ui/app.py:2386-2388` CORS `*` | No auth-by-default API enforcement found in repo | High |
| `configs/news-livecheck-ng.yaml:38-49` (`news_llm.enabled: false`) | LLM-related config is present but disabled and not wired to a visible runtime implementation | Medium |

Platform pattern assessment:
- Closest fit: **Self-hosted / mixed**, with Codex-style repository governance artifacts.
- Not found as primary platform: OpenAI Agents SDK, AWS Bedrock AgentCore, Vertex Agent Engine, Copilot Studio runtime contracts.

## 3) Scorecard AO-01…AO-30

| ID | Status | Risk | Evidence | Remediation |
| --- | --- | --- | --- | --- |
| AO-01 | FAIL | Medium | No MCP/protocol artifacts (`rg ... mcp|model context protocol` -> no hits); only repo skills (`AGENTS.md:38-74`). | Define MCP/equivalent tool contract schema; add compatibility tests in CI; migrate tool adapters to this contract. |
| AO-02 | PARTIAL | Medium | Skill list acts as lightweight registry (`AGENTS.md:38-53`, `scripts/validate_skills.py:51-129`), but no per-tool owners/restrictions metadata. | Create machine-readable tool registry (owner, scope, risk tier, allowed environments); enforce via validator; require owner approval for changes. |
| AO-03 | FAIL | High | No dedicated tool gateway/auth exchange plane; only UI proxy/API routes (`ui-web/vite.config.ts:14-15`, `src/moex_carry/ui/app.py:2586-5315`). | Introduce tool gateway service with authn/authz, credential brokering, and centralized audit logs; route all tool calls through it. |
| AO-04 | PARTIAL | Medium | Skill descriptions/frontmatter exist (`.cursor/skills/parallel-worktree-flow/SKILL.md:1-15`); validator checks description presence (`scripts/validate_skills.py:69-95`). | Add structured “when to use/never use/risk” fields; require examples and anti-examples; lint description quality. |
| AO-05 | FAIL | Medium | Tool routing is static/manual (`AGENTS.md:55-64`, `AGENTS.md:67-73`), no dynamic or semantic discovery engine. | Implement contextual tool selection service (capability tags + policy filters + semantic ranking); add fallback deterministic routing. |
| AO-06 | PARTIAL | Medium | Some toggles exist (`configs/default.yaml:159-171`, `configs/news-livecheck-ng.yaml:38-49`); action audit fields exist (`src/moex_carry/ui/app.py:4421-4524`); no admin/builder role separation. | Add RBAC for tool enable/disable; separate platform-admin vs agent-builder permissions; persist immutable audit trail for toggle changes. |
| AO-07 | PARTIAL | Medium | Session guard exists (`scripts/worktree_guard.ps1:1-189`), reproducibility IDs exist (`contracts/decision-log.schema.json:32-35`); this is mostly dev/process-level. | Add production session store for agent runs with replay payload snapshots; persist run manifests; expose run replay CLI/API. |
| AO-08 | FAIL | High | Long-term memory file exists (`memory/agent_memory.yaml`), validated structurally (`scripts/validate_agent_memory.py` via lean gate), but no formal forget/delete/poisoning controls. | Define memory lifecycle policy (write/read/delete TTL); add signed provenance for memory entries; add poisoning/anomaly checks. |
| AO-09 | FAIL | Medium | No managed example/few-shot store artifacts found (`rg ... few-shot|example store` -> no hits). | Introduce versioned example store with owner approvals and retrieval policies; add offline quality checks for example drift. |
| AO-10 | FAIL | High | No runtime code-exec sandbox primitives found; only operational runbook limits (`agent-runbook.md:16-67`). | Add isolated code-exec runtime (container/VM), CPU/memory/network caps, per-run audit logs, and kill-switch API. |
| AO-11 | FAIL | High | No privacy-preserving LLM-context policy found (`rg ... dlp|privacy|redact` -> no actionable controls). | Classify sensitive fields, implement context minimization/redaction before model calls, and default deny for sensitive intermediates. |
| AO-12 | FAIL | Medium | Browser automation appears only in test pipeline (`.github/workflows/ci.yml:255-284`), no isolated production browser/computer-use runtime. | If browser-use is needed, isolate in sandbox with URL allowlist, content filtering, and forensic logs. |
| AO-13 | PARTIAL | High | Some identity-like fields (`actor_id`, `source`) and consent flow for Telegram ACK (`src/moex_carry/integrations/telegram_worker.py:257-287,565-630`), but no unified production agent identity/auth plane. | Add service identities/workload auth for agents; prohibit maker credentials in prod paths; implement explicit consent/refresh contracts per risky action. |
| AO-14 | PARTIAL | Medium | API logging and SLO metrics exist (`src/moex_carry/logging.py:9-67`, `src/moex_carry/ui/app.py:2407-2434`, `src/moex_carry/observability/runtime_metrics.py:16-88`), but no full tool-call/handoff traces. | Define agent trace schema (steps, tool calls, handoffs, latencies, policy decisions); export to trace backend; add trace explorer docs. |
| AO-15 | FAIL | Medium | No trajectory-eval suite for expected tool paths found (`rg ... trajectory|tool calls expected` -> no implementation). | Add trajectory test datasets with expected action graphs; score path correctness in CI; block regressions. |
| AO-16 | PARTIAL | Medium | Runtime SLO endpoint exists (`src/moex_carry/ui/app.py:4743-4859`), CI quality checks exist (`.github/workflows/ci.yml:80-151`), but no continuous agent-quality evaluators in production. | Add production evaluators (online scorecards for behavior quality); monitor drift; alert on threshold breaches. |
| AO-17 | PARTIAL | Medium | Strong gates for docs/policies (`scripts/run_lean_gate.py:34-53`, `.github/workflows/ci.yml:45-106`), but no mandatory behavioral regression-eval for agent trajectories. | Add mandatory behavior regression suite for instruction/tool/policy changes; fail CI on quality regression; make agent-review blocking for critical findings. |
| AO-18 | FAIL | High | No auth middleware found (`rg ... jwt|oauth|Authorization` -> no hits); CORS wide open (`src/moex_carry/ui/app.py:2386-2388`). | Add authn/authz by default for API/tool endpoints; deny unauthenticated access; add detection/alerting for unauthenticated agent calls. |
| AO-19 | FAIL | High | Outbound URLs are config-driven without central allowlist (`src/moex_carry/config.py:14-31,198-212`, `src/moex_carry/integrations/telegram_worker.py:77-81,695-713`). | Enforce outbound domain/port allowlist at client wrapper + network policy; block AI/user-controlled critical endpoints; log deny events. |
| AO-20 | PARTIAL | Medium | Governed wrappers exist (`src/moex_carry/data/moex_iss.py:36-237`, `src/moex_carry/integrations/telegram_worker.py:64-724`), but raw HTTP remains in utility scripts (`scripts/acceptance_check.py`). | Route critical external calls through governed connectors only; ban direct `requests` in runtime paths via lint/policy; add connector-level audit IDs. |
| AO-21 | PARTIAL | High | Secret scan and gate exist (`scripts/scan_secrets.py:10-90`, `configs/quality_scorecards.yaml:14-17`), local secret files are gitignored (`.gitignore:12`), but no vault/rotation integration. | Integrate secrets manager (vault/KMS/KeyVault equivalent); automate rotation; ban long-lived plain env secrets in production runtime. |
| AO-22 | FAIL | High | No DLP policy/audit->block pipeline found in code/docs (`rg ... dlp|sensitive data protection` -> no controls). | Add DLP classification for input/output/memory writes; start in audit mode then block mode; track false positives/negatives. |
| AO-23 | FAIL | High | No prompt injection/jailbreak policy found (`rg ... prompt injection|jailbreak|indirect injection` -> no controls). | Add untrusted-content policy and injection detectors; isolate retrieval contexts; require policy checks before model/tool execution. |
| AO-24 | PARTIAL | Medium | Domain-level pre-execution policy interception exists for signal actions (`src/moex_carry/ui/app.py:4383-4412`, `src/moex_carry/domain/execution_policy.py:30-90`) but not generic tool-call enforcement. | Generalize interception to all tool calls (allow/deny/transform before side effects); centralize policy engine; emit policy decisions in trace. |
| AO-25 | PARTIAL | Medium | Multi-agent operational guardrails exist (`agent-runbook.md:16-67`), and risky Telegram ACK has human action (`src/moex_carry/integrations/telegram_worker.py:565-630`), but no policy inheritance for sub-agents. | Add formal multi-agent policy inheritance model and role constraints; require HIL for high-risk categories; audit sub-agent delegation. |
| AO-26 | PARTIAL | Medium | Release/process safety strong (`.githooks/pre-push:19-77`, `.github/workflows/ci.yml:285-324`, `.github/pull_request_template.md:12-37`), but runtime rollback mechanism is mostly procedural. | Version runtime configs/endpoints explicitly; add rollback playbook with tested automation; include canary/quick revert criteria. |
| AO-27 | FAIL | High | Agent behavior is repo-instruction driven (`AGENTS.md`, `.cursor/skills/*`); no cryptographic/pinned trust boundary for instruction sources. | Introduce trusted baseline for agent policy files (signed/pinned); ignore untrusted repo overrides by default; enforce protected config channels. |
| AO-28 | PARTIAL | Medium | Ownership/governance exist (`CODEOWNERS`, `plans/PLANS.yaml` owner fields, scheduled docs/self-heal workflows), but no orphaned/dormant agent detector. | Add inventory and lifecycle scanner for dormant/orphaned agents/tools; require periodic access/ownership recertification; auto-create cleanup tasks. |
| AO-29 | PARTIAL | Medium | Progressive disclosure/context-budget controls exist (`docs/workflows/context-budget.md:7-25`, `.cursorignore`, `agent-runbook.md`), but no enforced token/intermediate-result budgets for agent tool-plane. | Add token/result-size budgets per tool/model call; enforce truncation/summarization policy; publish latency/token dashboards. |
| AO-30 | PARTIAL | Medium | Transport resilience exists (timeouts/retries/fallback TLS host validation in `src/moex_carry/data/moex_iss.py:13-237`; timeouts in Telegram worker), but no mTLS/deadline propagation/gRPC plane. | Add secure transport policy (mTLS where needed), request deadlines and cancellation propagation, and standardized tool-call transport contracts. |

## 4) Findings by sections A–F

### A. Tool-plane
- The repository has a **development skill catalog** with validation (`AGENTS.md`, `.cursor/skills`, `scripts/validate_skills.py`), but no production-grade MCP/equivalent standardized tool protocol.
- Tool routing is static (flow order and manual invocation rules), not dynamic or contextual.
- No central tool gateway with auth exchange and pre-execution policy controls was found.

### B. Runtime primitives
- There are good reproducibility/process artifacts (`worktree_guard`, `run_id`, decision schemas), but they are mostly dev/process-level rather than agent runtime session primitives.
- Memory is maintained as YAML governance memory, not a protected agent memory subsystem with poisoning and delete semantics.
- Browser/computer-use and sandboxed code-exec runtime controls are absent as platform primitives.

### C. Trace & evaluation
- API observability is present (structured request logs and SLO endpoints), but this is not equivalent to full agent trajectory tracing.
- CI gates are strong for governance and quality, yet they do not evaluate agent action trajectories.
- Agent review exists, but is primarily advisory for non-P0 findings.

### D. Security/policy
- Critical gap: no auth-by-default enforcement was found for API routes.
- Outbound calls are not governed by a central allowlist policy.
- Secret hygiene has baseline controls (scan + gitignore), but no vault/rotation production standard.
- DLP and prompt-injection controls are not implemented.

### E. Multi-agent, releases, trust boundaries
- Release governance is mature for repo changes (PR-only, CI checks, release-note fragment gating).
- Multi-agent runtime governance is mostly operational/runbook-based, not policy-engine based.
- Repo instructions can modify agent behavior; trust boundary against untrusted instruction sources is not formally hardened.

### F. Performance & cost
- Context-budget and high-load runbook practices are strong for human/agent development workflows.
- Tool-plane token/latency/cost governance is not yet formalized for a production agent runtime.
- Transport reliability patterns exist (timeouts/retries), but advanced secure transport controls are incomplete.

## 5) Top issues (<=10)
1. **No auth-by-default for API/tool endpoints (AO-18, High)**: unauthenticated access risk to operational actions.
2. **No standardized production tool-plane (AO-01/AO-03, High)**: difficult governance, policy, and safe scaling.
3. **No outbound allowlist governance (AO-19, High)**: potential SSRF/data-exfiltration surface via configurable endpoints.
4. **No DLP pipeline (AO-22, High)**: sensitive data can move without audit/block controls.
5. **No prompt injection/jailbreak controls (AO-23, High)**: unsafe if/when LLM paths are enabled.
6. **No trajectory evaluation gates (AO-15/AO-17, Medium)**: behavior regressions can ship unnoticed.
7. **No protected trust boundary for instruction/config sources (AO-27, High)**: repo-level instruction drift can alter agent behavior.
8. **Secrets management lacks vault+rotation (AO-21, High)**: baseline hygiene exists, but not production-grade lifecycle control.
9. **No generic pre-tool-call policy interception plane (AO-24, Medium)**: current policy checks are domain-specific only.
10. **No sandboxed code-exec/browser runtime primitives (AO-10/AO-12, Medium-High)**: high-risk capabilities are not platform-isolated.

## 6) Recommendations (Top-10, sorted by Impact/Cost)

| Priority | Recommendation | AO IDs | Impact | Cost |
| --- | --- | --- | --- | --- |
| R1 | Add API/tool authn+authz by default (service identity + RBAC + deny unauth) | AO-18, AO-13 | Very High | Medium |
| R2 | Implement centralized outbound allowlist policy (app + network) | AO-19, AO-20, AO-30 | Very High | Medium |
| R3 | Introduce tool gateway with pre-exec policy interception | AO-03, AO-24 | Very High | Medium-High |
| R4 | Define machine-readable tool registry with owners/risk/restrictions | AO-01, AO-02, AO-06 | High | Medium |
| R5 | Add DLP pipeline (audit->block) for model/tool I/O and memory writes | AO-11, AO-22 | High | Medium-High |
| R6 | Add prompt-injection/jailbreak defense policy and detectors | AO-23 | High | Medium |
| R7 | Add trajectory-eval datasets and blocking CI gates | AO-15, AO-17, AO-16 | High | Medium |
| R8 | Integrate vault-backed secrets and rotation policy | AO-21 | High | Medium |
| R9 | Harden trust boundary for instruction/policy files (signed/pinned baseline) | AO-27 | High | Medium |
| R10 | Add formal multi-agent lifecycle scanner (orphan/dormant) and recertification | AO-28, AO-25 | Medium | Low-Medium |

## 7) Manual follow-ups (requires external access)
- Verify GitHub branch protection and required checks enforcement for `main` in org settings.
- Validate production runtime deployment topology (service mesh, mTLS, egress firewall) outside repo.
- Confirm whether an external secrets manager/rotation exists and is actually bound to runtime.
- Confirm whether any external SIEM/trace backend captures tool-call trajectories.
- Validate cloud-side policy engines (if any) for pre-execution allow/deny on side-effecting calls.
- Validate production dashboards/alerts for model/tool quality degradation (not only API latency).

## 8) Appendix: commands executed (minimal)
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\worktree_guard.ps1 -Action Check` -> context expired.
- `git rev-parse --abbrev-ref HEAD; git rev-parse --short HEAD`
- `git ls-files | Measure-Object`
- `rg -n --ignore-case "mcp|model context protocol|..." .`
- `rg -n --ignore-case "auth|oauth|jwt|Authorization|..." src pyproject.toml`
- `python scripts/run_lean_gate.py` -> `lean gate: OK`.
- `python scripts/scan_secrets.py` -> `secret scan: OK`.
- Targeted reads of: `AGENTS.md`, `docs/DEV_WORKFLOW.md`, `harness-guideline.md`, `.github/workflows/*.yml`, `src/moex_carry/ui/app.py`, `src/moex_carry/data/moex_iss.py`, `src/moex_carry/integrations/telegram_worker.py`, `configs/*.yaml`, `scripts/*.py`.

## Coverage note
- `worktree_guard` preflight succeeded technically only up to `Check`; context was expired and was not re-initialized in this audit due strict read-mostly constraint.
