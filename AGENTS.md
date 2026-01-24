# AGENTS.md instructions for d:\New Project

<INSTRUCTIONS>
## Skills
A skill is a set of local instructions to follow that is stored in a `SKILL.md` file. Below is the list of skills that can be used. Each entry includes a name, description, and file path so you can open the source for full instructions when using a specific skill.
### Available skills
- frontend-behavior-check: Verifies trading UI behavior via API smoke checks, Vite proxy validation, chart data checks, and basic table expectations. Use when frontend/UI/React/Vite/MUI table or chart changes are made, or when the user asks to validate the UI. (file: D:/New Project/.cursor/skills/frontend-behavior-check/SKILL.md)
- intraday-futures-trading-advisor: Provides intraday futures trading strategy guidance focused on commissions, taxes, risk management, and portfolio risk allocation. Use when the user asks for intraday trading advice, futures strategies, cost accounting, or portfolio risk distribution. (file: D:/New Project/.cursor/skills/intraday-futures-trading-advisor/SKILL.md)
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
