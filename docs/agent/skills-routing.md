# Skills Routing (Hot Summary)

## Trigger Rule
- If a user names a skill, or request clearly matches a skill intent, use it in the same turn.
- Do not carry skills across turns unless re-mentioned.

## Flow Order (mandatory)
1. Start with `parallel-worktree-flow`.
2. UI chain: `trading-ui-dashboard` -> `ui-decision-log` -> `frontend-behavior-check`.
3. Strategy chain: `intraday-futures-trading-advisor` -> `moex-instruments-costs` -> `risk-profile-gates`.
4. News chain: `commodity-news-linking` -> `news-impact-backtest-lab` -> `signals-news-bridge-v2`.
5. Research/perf: `ml-backtest-hpo-lab`; add `minute-candle-performance` for high-load paths.

## Governance for Skills
- Canonical workflow: `docs/workflows/skill-governance-sync.md`
- Validate after changes: `python scripts/validate_skills.py`
- Skill update routing decision:
  - `python scripts/skill_update_decision.py --from-git --request "intent"`

## Full Catalog
- Use `docs/agent/skills-catalog.md` for complete skill-to-path mapping.
