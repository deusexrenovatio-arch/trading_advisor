# AGENTS.md for d:\New Project

<INSTRUCTIONS>
## Intent (Harness-Oriented)
- This file is a routing map, not a full handbook.
- Keep context small and rely on mechanical checks.
- Reference philosophy: https://openai.com/index/harness-engineering/
- Source-of-truth files:
  - `docs/README.md`
  - `docs/DEV_WORKFLOW.md`
  - `docs/workflows/context-budget.md`
  - `docs/session_handoff.md`
  - `harness-guideline.md`
  - `plans/PLANS.yaml`
  - `memory/agent_memory.yaml`
  - `CODEOWNERS`
  - `docs/checklists/first-time-right-gate.md`
  - `docs/runbooks/governance-remediation.md`
  - `scripts/run_lean_gate.py`

## Non-Negotiable Loop
1) Verify worktree context with `./scripts/worktree_guard.ps1 -Action Check`.
2) Before and after meaningful patches run `python scripts/run_lean_gate.py`.
3) Keep `plans/PLANS.yaml` statuses aligned with actual progress.
4) Keep `memory/agent_memory.yaml` updated with durable decisions/incidents/patterns.
  - incidents must use remediation types from `configs/agent_incident_policy.yaml`.
5) Keep `docs/session_handoff.md` updated and pass `python scripts/validate_session_handoff.py`.
6) Before push run blocker checks from `docs/DEV_WORKFLOW.md`.
  - include `python scripts/validate_quality_scorecards.py`.
7) Use PR-only flow for `main`: feature branch -> PR -> merge.
  - direct push to `main` is blocked by `.githooks/pre-push`.
  - emergency override requires both:
    - `MOEX_CARRY_EMERGENCY_MAIN_PUSH=1`
    - `MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON='<ticket/incident>'`
8) Any failing gate is a blocker; fix first, continue after.
  - use `docs/runbooks/governance-remediation.md` for deterministic fixes.

## Skills
### Available skills
- commodity-news-linking: Deterministic news-to-entity linking workflow. (file: .cursor/skills/commodity-news-linking/SKILL.md)
- frontend-behavior-check: UI smoke checks for API/proxy/chart/table behavior. (file: .cursor/skills/frontend-behavior-check/SKILL.md)
- intraday-futures-trading-advisor: Intraday futures strategy guidance and risk/cost framing. (file: .cursor/skills/intraday-futures-trading-advisor/SKILL.md)
- minute-candle-performance: High-load minute-candle performance workflow. (file: .cursor/skills/minute-candle-performance/SKILL.md)
- ml-backtest-hpo-lab: End-to-end backtest/HPO experiment workflow. (file: .cursor/skills/ml-backtest-hpo-lab/SKILL.md)
- moex-instruments-costs: MOEX futures cost model and break-even checks. (file: .cursor/skills/moex-instruments-costs/SKILL.md)
- news-geopolitics-filter: Deterministic high-impact event risk gate. (file: .cursor/skills/news-geopolitics-filter/SKILL.md)
- news-impact-backtest-lab: News-impact model evaluation workflow. (file: .cursor/skills/news-impact-backtest-lab/SKILL.md)
- parallel-worktree-flow: Multi-worktree bootstrap and sync routine. (file: .cursor/skills/parallel-worktree-flow/SKILL.md)
- risk-profile-gates: Deterministic intraday risk profile gates. (file: .cursor/skills/risk-profile-gates/SKILL.md)
- signals-news-bridge-v2: Bridge for news-impact and signal lifecycle APIs. (file: .cursor/skills/signals-news-bridge-v2/SKILL.md)
- spread-arbitrage: Deterministic pair-spread checklist/template. (file: .cursor/skills/spread-arbitrage/SKILL.md)
- trading-ui-dashboard: Production UI workflow for trading dashboard. (file: .cursor/skills/trading-ui-dashboard/SKILL.md)
- ui-decision-log: Decision log/view projection workflow and checks. (file: .cursor/skills/ui-decision-log/SKILL.md)

### Flow Order (mandatory)
- Start: `parallel-worktree-flow`.
- UI: `trading-ui-dashboard` -> `ui-decision-log` -> `frontend-behavior-check`.
- Strategy: `intraday-futures-trading-advisor` -> `moex-instruments-costs` -> `risk-profile-gates`.
  - Add `news-geopolitics-filter` for event-risk gating.
  - Add `spread-arbitrage` for pair-spread logic.
- News/signal: `commodity-news-linking` -> `news-impact-backtest-lab` -> `signals-news-bridge-v2`.
- Research/performance: `ml-backtest-hpo-lab`; add `minute-candle-performance` for high-load paths.
- Recheck and pre-push: rerun active verification skills and required checks from `docs/DEV_WORKFLOW.md`.
  - dependency or abstraction changes must include ADR updates under `docs/architecture/adr/`.

### Skill Usage Rules
- If user names a skill (or task clearly matches), use that skill in the same turn.
- Do not carry skills across turns unless re-mentioned.
- Read skills with progressive disclosure:
  1) open `SKILL.md`;
  2) load only required references;
  3) prefer existing scripts/templates over manual duplication.
- Keep context budget tight: avoid bulk file dumps and deep reference chasing.

## First-Time-Right Protocol (mandatory)
- Applies to research and user-facing business logic.
- Run `docs/checklists/first-time-right-gate.md` before implementation and before pre-push.
- Required report block:
  1) Confirmed coverage.
  2) Missing or risky scenarios.
  3) Resource/time risks and controls.
  4) Highest-priority fixes or follow-ups.

## Worktree Safety Protocol (mandatory)
- Before any code edits or long-running commands, run:
  - `./scripts/worktree_guard.ps1 -Action Check`
- If context is missing, initialize:
  - `./scripts/worktree_guard.ps1 -Action Init -WorktreePath "<path>" -Branch "<branch>" -ContextTtlHours 12`
- If `Check` reports mismatch, stop and switch to expected worktree/branch.
- If context expired, re-run `Init` before development actions.
- Use `./scripts/worktree_guard.ps1 -Action Show` when reporting active context.
</INSTRUCTIONS>
