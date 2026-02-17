# AGENTS.md instructions for d:\New Project

<INSTRUCTIONS>
## Skills
A skill is a set of local instructions to follow that is stored in a `SKILL.md` file. Below is the list of skills that can be used. Each entry includes a name, description, and file path so you can open the source for full instructions when using a specific skill.

### Available skills
- frontend-behavior-check: Verifies trading UI behavior via API smoke checks, Vite proxy validation, chart data checks, and table expectations. Use after frontend/UI/React/Vite/MUI changes, during regression rechecks, and as a pre-push gate for UI branches. (file: D:/New Project/.cursor/skills/frontend-behavior-check/SKILL.md)
- intraday-futures-trading-advisor: Provides intraday futures strategy guidance with commissions, taxes, risk controls, and portfolio risk allocation. Use for intraday/futures/cost/risk planning and co-use with deterministic risk/cost/news gates. (file: D:/New Project/.cursor/skills/intraday-futures-trading-advisor/SKILL.md)
- parallel-worktree-flow: Baseline multi-stream development workflow with git worktree, branch isolation, rebase routine, and integration sync. Use at the start of new development, when coordinating parallel streams, and before merge/push synchronization. (file: D:/New Project/.cursor/skills/parallel-worktree-flow/SKILL.md)
- minute-candle-performance: Performance engineering workflow for high-volume minute-candle computation (stack policy, replay acceleration, cache, chunking, deterministic parallelization). Use for optimization, runtime scaling, minute replay, and performance rechecks before push. Use together with `architecture-review` when boundaries/dependencies change. (file: D:/New Project/.cursor/skills/minute-candle-performance/SKILL.md)
- ml-backtest-hpo-lab: End-to-end research workflow for Backtest v2, forward checks, HPO runs, leakage-safe walk-forward validation, stress tests, and promotion decisions. Use for backtest/HPO/forward tasks and for mandatory experiment rechecks before push. (file: D:/New Project/.cursor/skills/ml-backtest-hpo-lab/SKILL.md)
- moex-instruments-costs: Deterministic MOEX futures cost model template and break-even checks. Use whenever strategy costs/taxes change and during strategy recheck before push. (file: D:/New Project/.cursor/skills/moex-instruments-costs/SKILL.md)
- news-geopolitics-filter: Deterministic gate for high-impact news and geopolitics events. Use whenever event risk may block/reduce strategy actions and during strategy rechecks. (file: D:/New Project/.cursor/skills/news-geopolitics-filter/SKILL.md)
- risk-profile-gates: Deterministic risk profile gates for intraday futures decisions. Use for risk-limit validation and as a mandatory strategy pre-push gate. (file: D:/New Project/.cursor/skills/risk-profile-gates/SKILL.md)
- spread-arbitrage: Deterministic spread arbitrage checklist and JSON plan template. Use for pair-spread strategies and co-use with risk/cost/news gates. (file: D:/New Project/.cursor/skills/spread-arbitrage/SKILL.md)
- trading-ui-dashboard: Build production-grade trading advisor UI with React/Vite/TypeScript, MUI, and AG Grid. Use for dashboard/readability/filter/drill-down tasks; co-use with `ui-decision-log` and `frontend-behavior-check` for validation and pre-push rechecks. (file: D:/New Project/.cursor/skills/trading-ui-dashboard/SKILL.md)
- ui-decision-log: UI projection and deterministic checks for `decision_log` -> `decision_view`. Use for projection/contract updates and co-use with UI build and frontend behavior rechecks. (file: D:/New Project/.cursor/skills/ui-decision-log/SKILL.md)

### Lifecycle dependencies (mandatory)
- Start of new development: invoke `parallel-worktree-flow` first for branch/worktree bootstrap.
- UI flow: use `trading-ui-dashboard`, then `ui-decision-log`, then `frontend-behavior-check`.
- Strategy flow: use `intraday-futures-trading-advisor`, then `moex-instruments-costs`, then `risk-profile-gates`; add `news-geopolitics-filter` for event-risk gating; add `spread-arbitrage` for pair-spread logic.
- Research/performance flow: use `ml-backtest-hpo-lab`; add `minute-candle-performance` for minute/high-load workloads.
- Recheck stage: rerun verification skills in the active flow and run required checks from `docs/DEV_WORKFLOW.md`.
- Pre-push stage: run all required checks from `docs/DEV_WORKFLOW.md`; treat any failure as a blocker.
- If several skills apply, execute in order: bootstrap -> domain design -> verification/recheck -> pre-push gate.

### How to use skills
- Discovery: The list above is the skills available in this session (name + description + file path). Skill bodies live on disk at the listed paths.
- Trigger rules: If the user names a skill (with `$SkillName` or plain text) OR the task clearly matches a skill's description shown above, you must use that skill for that turn. Multiple mentions mean use them all. Do not carry skills across turns unless re-mentioned.
- Missing/blocked: If a named skill is not in the list or the path cannot be read, say so briefly and continue with the best fallback.
- How to use a skill (progressive disclosure):
  1) After deciding to use a skill, open its `SKILL.md`. Read only enough to follow the workflow.
  2) If `SKILL.md` points to extra folders such as `references/`, load only the specific files needed for the request; do not bulk-load everything.
  3) If `scripts/` exist, prefer running or patching them instead of retyping large code blocks.
  4) If `assets/` or templates exist, reuse them instead of recreating from scratch.
- Coordination and sequencing:
  - If multiple skills apply, choose the minimal set that covers the request and state the order you use them.
  - Announce which skill(s) you use and why (one short line). If you skip an obvious skill, say why.
- Context hygiene:
  - Keep context small: summarize long sections instead of pasting them; only load extra files when needed.
  - Avoid deep reference-chasing: prefer opening only files directly linked from `SKILL.md` unless blocked.
  - When variants exist (frameworks, providers, domains), pick only relevant reference files and note that choice.
- Safety and fallback: If a skill cannot be applied cleanly (missing files, unclear instructions), state the issue, pick the next-best approach, and continue.
</INSTRUCTIONS>

## Worktree Safety Protocol (mandatory)
- Before any code edits or long-running commands, run:
  - `./scripts/worktree_guard.ps1 -Action Check`
- If guard context is not initialized, stop and ask the user which worktree/branch must be used, then initialize:
  - `./scripts/worktree_guard.ps1 -Action Init -WorktreePath "<path>" -Branch "<branch>" -ContextTtlHours 12`
- If `Check` reports mismatch, stop immediately and switch to the expected worktree/branch before continuing.
- If `Check` reports expired context, re-run `Init` before any development actions.
- Use `./scripts/worktree_guard.ps1 -Action Show` when reporting current session context.
