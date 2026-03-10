# Agent-Only Production Readiness Backlog

| Item | AO-ID | Owner (Platform/Security/App) | Impact | Cost | Dependencies | Definition of Done |
| --- | --- | --- | --- | --- | --- | --- |
| Build standardized tool contract (MCP-equivalent) and schema tests | AO-01 | Platform | High | Medium | None | Tool contract spec versioned; 100% runtime tools conform; CI blocks non-conformant tools. |
| Create machine-readable tool registry with owner/risk/allowed-env metadata | AO-02, AO-06 | Platform | High | Medium | Tool contract baseline | Registry file exists; each tool has owner+risk tier+enabled scopes; validator blocks missing metadata. |
| Introduce tool gateway/proxy with authn/authz and credential exchange | AO-03, AO-24 | Platform + Security | Very High | High | Tool registry, service identity | All side-effecting tool calls go through gateway; policy decisions logged before execution. |
| Add structured tool description quality rules (when-use/never-use/examples) | AO-04 | App + Platform | Medium | Low | Tool registry | Description linter in CI; weak/ambiguous descriptions fail checks. |
| Implement contextual/dynamic tool selection service | AO-05 | Platform + App | High | Medium-High | Registry + gateway | Runtime selects tools by context and policy, not static prompt bundles; fallback deterministic route covered by tests. |
| Add auth-by-default to API/tool endpoints and unauth access detection | AO-18, AO-13 | Security + Platform | Very High | Medium | Identity provider/service auth | Unauthenticated requests rejected by default; auth events and anomalies visible in alerts. |
| Enforce outbound allowlist + deny AI/user-controlled critical endpoints | AO-19, AO-20, AO-30 | Security + Platform | Very High | Medium | Gateway or client wrapper hardening | Outbound domain/port policy enforced in code + network; blocked attempts audited. |
| Integrate secrets manager + rotation workflow (remove prod plain env secrets) | AO-21 | Security + Platform | High | Medium | Identity/auth foundation | Secrets sourced from vault/KMS/KeyVault in production; rotation runbook + automated checks exist. |
| Add DLP pipeline for input/output and memory writes (audit->block) | AO-22, AO-11 | Security + App | High | Medium-High | Data classification model | Sensitive fields classified and redacted/blocked per policy; metrics on DLP decisions collected. |
| Add prompt injection/jailbreak/indirect-injection protections | AO-23 | Security + App | High | Medium | DLP baseline, untrusted-content policy | Injection tests and detectors in CI and runtime; policy denies unsafe execution paths. |
| Implement full agent trace schema + storage + explorer | AO-14 | Platform | High | Medium | Gateway/policy interception | Trace includes tool calls, handoffs, latencies, policy outcomes; export and query interfaces available. |
| Add trajectory eval and regression gates for tool/action paths | AO-15, AO-17, AO-16 | App + Platform | High | Medium | Agent trace schema | Trajectory datasets versioned; CI fails on path regression; production drift monitors active. |
| Add sandboxed code-exec and browser-use runtime isolation with resource/network caps | AO-10, AO-12, AO-25 | Platform + Security | High | High | Gateway, auth, policy plane | High-risk capabilities run only in isolated sandbox with audit logs and kill-switch. |
| Harden trust boundary for instruction/config sources (signed baseline) | AO-27 | Security + Platform | High | Medium | Release governance baseline | Agent ignores untrusted instruction overrides by default; signed policy files enforced in CI/runtime. |
| Add lifecycle governance scanner for orphaned/dormant agents/tools | AO-28 | Platform | Medium | Low-Medium | Tool registry | Scheduled scanner reports stale owners/dormant tools; auto-created remediation tasks tracked to closure. |
| Add token/result-size latency budgets for tool/model calls | AO-29 | App + Platform | Medium | Medium | Trace + eval metrics | Per-tool budgets enforced; over-budget calls trigger degrade/abort policy and alerts. |
| Strengthen release safety with tested rollback automation for runtime configs | AO-26 | Platform + App | Medium | Medium | CI + versioned configs | Rollback playbook executable in staging; recovery time objective validated in drills. |

## Quick wins (<=1-2 days)
1. Make instruction/tool-policy changes block CI unless `validate_skills` + dedicated agent-behavior smoke tests pass.
2. Add explicit outbound allowlist config skeleton and deny-by-default branch in runtime HTTP wrappers.
3. Add security policy doc for prompt injection/DLP threat model and link it into mandatory workflow checks.
4. Add check to fail if local secret files are accidentally tracked (`scripts/*.local.ps1` guard in CI).

## Strategic (>=2 weeks)
1. Build full tool gateway + policy interception + trace plane.
2. Implement sandboxed execution/browser runtime with formal risk tiers and HIL controls.
3. Deploy continuous trajectory evaluation in production with drift alerting.
4. Establish signed trust boundary for agent instruction/config artifacts.
