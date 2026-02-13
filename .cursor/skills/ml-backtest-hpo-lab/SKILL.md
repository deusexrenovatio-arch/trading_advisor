---
name: ml-backtest-hpo-lab
description: "End-to-end research workflow for data-analyst and ML-engineer tasks in this MOEX carry repository: Backtest v2, forward checks, HPO runs, leakage-safe walk-forward validation, objective/metric sanity checks, robustness stress tests, and experiment reporting. Use when requests mention backtest, forward test, walk-forward, CV folds, embargo, HPO, hyperparameter search, overfitting, leakage, model or strategy evaluation, or experiment comparison."
---

# ML Backtest HPO Lab

## Overview
Use this skill to run reproducible strategy research cycles in this repository. Optimize for trustworthy out-of-sample quality, not in-sample leaderboard gains.

## Repository anchors
- Read `docs/hpo-howto.md` for project-specific HPO flow and payload examples.
- Read `docs/architecture/trading-advisor.md` for boundaries and deterministic guarantees.
- Use `src/moex_carry/contracts/strategy_test.py` as the source of truth for request schema.
- Use `src/moex_carry/hpo/objective.py` for metric/objective behavior and edge cases.
- Use `references/evaluation-checklist.md` for reporting and acceptance gates.
- For high-load runtime architecture and stack decisions, use `minute-candle-performance` skill.

## Workflow
1. Define the experiment contract before running compute:
- State hypothesis in one line.
- Freeze objective metric and mode (`max` or `min`).
- Freeze hard constraints (for example max drawdown or turnover).
- Freeze the time window and execution mode (`INTRADAY_MINUTE`, `DAILY_*`).

2. Reproduce baseline first:
- Run baseline Backtest v2 with default or explicit request payload.
- Keep config, request payload, and output artifact together for reproducibility.
- Use command examples:

```bash
python -m moex_carry.cli backtest_v2 --config configs/default.yaml --json
python -m moex_carry.cli backtest_v2 --config configs/default.yaml --request configs/hpo_request.yaml --precompute true --json
```

3. Enforce split hygiene and leakage control:
- Keep train, validation, and test strictly chronological.
- Use embargo days for close temporal dependence (`cv.embargo_days`).
- Treat `cv.purged` as declarative only; enforce leakage control via explicit windows and embargo.
- Inspect `folds_meta` in HPO status/result. If `folds_meta.fallback=true`, report that fold lengths were auto-scaled and confidence is lower.

4. Run HPO as controlled search:
- Start with small `max_trials` to validate payload and signal path.
- Use dotted keys in `search_space` (for example `strategy.z_window`).
- Prefer narrow, meaningful ranges around baseline before widening.
- Use async endpoints for long runs:
  - `POST /api/hpo/run`
  - `GET /api/hpo/status?run_id=...`

5. Evaluate by fold and out-of-sample:
- Compare fold dispersion, not only aggregated score.
- Report validation and test metrics separately per fold.
- Use robust aggregation (`median` or `p25`) when variance is high.
- Remember: `MaxDD` in raw metrics is negative, while objective logic normalizes it as absolute magnitude.

6. Stress-test robustness:
- Re-run with cost pressure (`test.cost_stress_mult`).
- Re-run with stricter execution assumptions (`execution_lag_minutes`, slippage, spread parameters).
- Check if top configs remain acceptable under stress, not only in nominal conditions.

7. Confirm forward readiness:
- Start forward run from same base config before recommending rollout.
- Verify behavior drift between backtest and forward loop is explained.
- Block rollout if drawdown, turnover, or execution quality degrades materially.

8. Deliver decision-ready report:
- Include baseline vs candidate vs stressed candidate.
- Include leakage/split notes, fold count, fallback usage, and remaining risks.
- Use the template in `references/evaluation-checklist.md`.

## Minimum validation commands
```bash
pytest -q tests/hpo tests/backtest_v2 tests/test_backtest_forward_api.py tests/test_forward_engine.py
```

## Guardrails
- Do not rank models by a single in-sample metric.
- Do not merge parameter changes with no out-of-sample evidence.
- Do not hide fallback folds or data-window shrinkage in summaries.
- Prefer deterministic, replayable commands and checked-in request payloads.
- Explicitly flag assumptions when data is incomplete.

## Output format
```markdown
## Experiment scope
- Hypothesis:
- Data window:
- Execution mode:
- Objective + constraints:

## Results
- Baseline:
- Best candidate:
- Stress candidate:
- Fold dispersion notes:

## Leakage and split audit
- Fold plan:
- Embargo:
- Fallback used (true/false):

## Recommendation
- Promote / hold:
- Why:
- Risks and follow-ups:
```
