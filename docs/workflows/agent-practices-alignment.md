# Agent Practices Alignment

Updated: 2026-03-04

## Sources
- https://guides.gritai.studio/guides/boris-way.html
- https://code.claude.com/docs/en/best-practices
- https://github.com/ykdojo/claude-code-tips

Detailed advice-by-advice traceability map:
- `docs/workflows/external-advice-mapping-2026-03-04.md`

## Observed external strengths
- Strong emphasis on high-quality task framing before coding.
- Aggressive context hygiene (reset/compact, focused files, avoid drift).
- Explicit plan-first and checklist-first execution.
- Tight operator feedback loop: early course-correction and explicit rejection of vague requests.

## Existing repository strengths
- Deterministic governance loop (`run_loop_gate.py` + validators).
- Worktree safety, PR-only policy, ownership routing, and memory/handoff discipline.
- First-time-right checklist and machine-readable plans/memory.

## Gaps found
- First-time-right report format was required in docs but not machine-validated.
- No hard gate for request quality in session handoff.
- Operator request contract expectations were implicit and easy to bypass.
- Repeated-issue handling required deep review but did not force behavior change evidence or search-space reset.

## Adopted now (machine-enforced)
- Added `python scripts/validate_task_request_contract.py`.
- Added mandatory `## Task Request Contract` and `## First-Time-Right Report` sections in session handoff.
- Added mandatory `## Repetition Control` section in session handoff to stop same-path overfitting.
- Wired the new validator into `python scripts/run_loop_gate.py --from-git --git-ref HEAD`.
- Extended `python scripts/validate_agent_memory.py` + `configs/agent_incident_policy.yaml` with required learning fields for new incidents.
- Updated remediation docs and governance validators to keep this check non-optional.

## Long-horizon controls
1. Introduce request-quality scorecard trend (`pass/fail`, missing-item frequency) in governance dashboard.
2. Add CI comment bot that flags PRs lacking explicit request contract to acceptance mapping.
3. Add reusable request templates per stream (UI, strategy, research) with minimal required fields only.

