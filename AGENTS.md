# AGENTS.md instructions for d:\New Project

<INSTRUCTIONS>
## Skills
A skill is a set of local instructions to follow that is stored in a `SKILL.md` file. Below is the list of skills that can be used. Each entry includes a name, description, and file path so you can open the source for full instructions when using a specific skill.
### Available skills
- frontend-behavior-check: Verifies trading UI behavior via API smoke checks, Vite proxy validation, chart data checks, and basic table expectations. Use when frontend/UI/React/Vite/MUI table or chart changes are made, or when the user asks to validate the UI. (file: D:/New Project/.cursor/skills/frontend-behavior-check/SKILL.md)
- intraday-futures-trading-advisor: Provides intraday futures trading strategy guidance focused on commissions, taxes, risk management, and portfolio risk allocation. Use when the user asks for intraday trading advice, futures strategies, cost accounting, or portfolio risk distribution. (file: D:/New Project/.cursor/skills/intraday-futures-trading-advisor/SKILL.md)
- parallel-worktree-flow: Baseline multi-stream development workflow for this repository using git worktree: clean bootstrap from main, branch-per-worktree isolation, daily rebase routine, integration branch checks, and merge ordering. Use when requests mention parallel development, several tasks at once, worktree, rebase strategy, branch synchronization, or conflict minimization. (file: D:/New Project/.cursor/skills/parallel-worktree-flow/SKILL.md)
- minute-candle-performance: Performance engineering workflow for high-volume candle computations in this repository: compute architecture and stack selection (numpy/numba/pandas boundaries), minute-candle ingestion, replay acceleration, cache design, chunking, and deterministic parallelization across pairs/scenarios. Use when requests mention optimization, performance, speed-up, parallelization, multiprocessing, bottlenecks, large candle exports, minute candles, heavy backtest batches, preload cache, runtime scaling, or architecture/stack choices for high-load calculations (РѕРїС‚РёРјРёР·Р°С†РёСЏ, РїР°СЂР°Р»Р»РµР»РёР·Р°С†РёСЏ, СѓР·РєРёРµ РјРµСЃС‚Р°, РјРёРЅСѓС‚РЅС‹Рµ СЃРІРµС‡Рё, Р±РѕР»СЊС€РёРµ РІС‹РіСЂСѓР·РєРё). Use together with `architecture-review` when module boundaries/dependencies are changed. (file: D:/New Project/.cursor/skills/minute-candle-performance/SKILL.md)
- ml-backtest-hpo-lab: End-to-end research workflow for data-analyst and ML-engineer tasks in this MOEX carry repository: Backtest v2, forward checks, HPO runs, leakage-safe walk-forward validation, objective/metric sanity checks, robustness stress tests, and experiment reporting. Use when requests mention backtest, forward test, walk-forward, CV folds, embargo, HPO, hyperparameter search, overfitting, leakage, model or strategy evaluation, or experiment comparison. (file: D:/New Project/.cursor/skills/ml-backtest-hpo-lab/SKILL.md)
- moex-instruments-costs: Cost model template and checks for MOEX futures instruments. (file: D:/New Project/.cursor/skills/moex-instruments-costs/SKILL.md)
- news-geopolitics-filter: Deterministic gate for high-impact news and geopolitics events. (file: D:/New Project/.cursor/skills/news-geopolitics-filter/SKILL.md)
- risk-profile-gates: Deterministic risk profile gates for intraday futures decisions. (file: D:/New Project/.cursor/skills/risk-profile-gates/SKILL.md)
- spread-arbitrage: Deterministic spread arbitrage checklist and JSON plan template. (file: D:/New Project/.cursor/skills/spread-arbitrage/SKILL.md)
- trading-ui-dashboard: Build production-grade trading advisor UI with React/Vite/TypeScript, MUI, and AG Grid. Use when improving dashboard readability, decision tables, filters, drill-down, or creating an API-backed UI for decision_log/decision_view. (file: D:/New Project/.cursor/skills/trading-ui-dashboard/SKILL.md)
- ui-decision-log: UI projection and checks for decision_log to decision_view. (file: D:/New Project/.cursor/skills/ui-decision-log/SKILL.md)
### How to use skills
- Discovery: The list above is the skills available in this session (name + description + file path). Skill bodies live on disk at the listed paths.
- Trigger rules: If the user names a skill (with `$SkillName` or plain text) OR the task clearly matches a skill's description shown above, you must use that skill for that turn. Multiple mentions mean use them all. Do not carry skills across turns unless re-mentioned.
- Missing/blocked: If a named skill isn't in the list or the path can't be read, say so briefly and continue with the best fallback.
- How to use a skill (progressive disclosure):
  1) After deciding to use a skill, open its `SKILL.md`. Read only enough to follow the workflow.
  2) If `SKILL.md` points to extra folders such as `references/`, load only the specific files needed for the request; don't bulk-load everything.
  3) If `scripts/` exist, prefer running or patching them instead of retyping large code blocks.
  4) If `assets/` or templates exist, reuse them instead of recreating from scratch.
- Coordination and sequencing:
  - If multiple skills apply, choose the minimal set that covers the request and state the order you'll use them.
  - Announce which skill(s) you're using and why (one short line). If you skip an obvious skill, say why.
- Context hygiene:
  - Keep context small: summarize long sections instead of pasting them; only load extra files when needed.
  - Avoid deep reference-chasing: prefer opening only files directly linked from `SKILL.md` unless you're blocked.
  - When variants exist (frameworks, providers, domains), pick only the relevant reference file(s) and note that choice.
- Safety and fallback: If a skill can't be applied cleanly (missing files, unclear instructions), state the issue, pick the next-best approach, and continue.
</INSTRUCTIONS>

