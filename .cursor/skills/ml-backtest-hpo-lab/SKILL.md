---
name: ml-backtest-hpo-lab
description: "End-to-end research workflow for this MOEX carry repository: Backtest v2, forward checks, HPO runs, leakage-safe walk-forward validation, objective sanity checks, stress tests, and experiment reporting. Use when requests mention backtest, forward test, walk-forward, CV folds, embargo, HPO, overfitting, leakage, or model/strategy comparison. Use for regression rechecks and pre-push quality gates on research changes."
---

# ML Backtest HPO Lab

## Overview
Use this skill to run reproducible strategy research cycles and prioritize trustworthy out-of-sample quality.

## Skill dependencies and lifecycle gates
- Start phase: run `parallel-worktree-flow` first for branch/worktree setup.
- Runtime/performance phase: add `minute-candle-performance` when minute/high-load compute behavior changes.
- Recheck phase: rerun this skill before closing any research bug or tuning task.
- Pre-push phase: ensure required checks from `docs/DEV_WORKFLOW.md` and research validation commands pass.


## Repository governance baseline (mandatory)
- Follow `docs/workflows/skill-governance-sync.md` for mandatory repository gates (worktree guard, lean loop, plans/memory/handoff, pre-push blockers, repeated-issue escalation).
- Keep this skill focused on domain workflow; do not duplicate repository governance details here.

## Repository anchors
- `docs/hpo-howto.md` for project-specific HPO flow and payload examples.
- `docs/research/evaluation-policy.md` for promotion criteria and evidence gates.
- `docs/architecture/trading-advisor.md` for deterministic boundary expectations.
- `src/moex_carry/contracts/strategy_test.py` as request schema source of truth.
- `src/moex_carry/hpo/objective.py` for objective behavior and edge cases.
- `references/evaluation-checklist.md` for report template and quality checklist.

## Workflow
1. Define experiment contract before compute:
- One-line hypothesis.
- Objective metric and mode (`max` or `min`).
- Hard constraints (for example drawdown/turnover caps).
- Fixed window and execution mode (`INTRADAY_MINUTE`, `DAILY_*`).

2. Reproduce baseline first:
- Run baseline Backtest v2 before changing params.
- Keep config, request payload, and artifact together.

```bash
python -m moex_carry.cli backtest_v2 --config configs/default.yaml --json
python -m moex_carry.cli backtest_v2 --config configs/default.yaml --request configs/hpo_request.yaml --precompute true --json
```

3. Enforce leakage-safe split hygiene:
- Keep train/validation/test strictly chronological.
- Set explicit embargo (`cv.embargo_days`) where serial dependence matters.
- Treat `cv.purged` as declarative; enforce windows explicitly.
- Inspect `folds_meta`; report when `folds_meta.fallback=true`.

4. Run HPO as controlled search:
- Start with low `max_trials` to validate payload and signal flow.
- Use dotted keys in `search_space` (for example `strategy.z_window`).
- Start near baseline ranges before widening.
- Use async endpoints for long runs:
  - `POST /api/hpo/run`
  - `GET /api/hpo/status?run_id=...`

5. Evaluate fold behavior and OOS quality:
- Compare fold dispersion, not only aggregate score.
- Report validation and test metrics separately by fold.
- Prefer robust summaries (`median` or `p25`) when variance is high.
- Remember `MaxDD` raw sign is negative; objective compares absolute magnitude.

6. Stress robustness:
- Re-run with cost stress (`test.cost_stress_mult`).
- Re-run with stricter execution assumptions (lag/slippage/spread).
- Keep candidates only if ranking and constraints hold under stress.

7. Confirm forward readiness:
- Initialize forward run from same base assumptions.
- Explain backtest vs forward drift.
- Block rollout if drawdown, turnover, or execution quality degrades materially.

8. Deliver decision-ready report:
- Include baseline, best candidate, stressed candidate.
- Include split/leakage notes, fold count, fallback usage, and residual risks.

## Minimum validation commands
```bash
python scripts/sync_architecture_map.py --check
pytest -q tests/hpo tests/backtest_v2 tests/test_backtest_forward_api.py tests/test_forward_engine.py
```

## Guardrails
- Do not rank models by a single in-sample metric.
- Do not merge parameter changes without OOS evidence.
- Do not hide fallback folds or window shrinkage.
- Prefer deterministic, replayable commands and checked-in payloads.
- Flag all assumptions explicitly when data is incomplete.

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
## Mandatory pre-push guidance
- Run `python scripts/sync_architecture_map.py --check` when boundaries or integrations are touched.
- Run required checks from `docs/DEV_WORKFLOW.md` for touched areas; treat failures as blockers.
- If contracts/registry/docs changed, update source-of-truth artifacts before push and keep notes in AGENTS or PR summary.
