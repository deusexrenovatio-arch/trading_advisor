---
name: news-impact-backtest-lab
description: "Evaluation workflow for news to price-impact models: dataset assembly, leakage-safe labeling, horizon metrics, calibration, and promotion gates. Use when running or changing news-impact backtests."
---

# News Impact Backtest Lab

## Purpose
Evaluate whether news signals predict futures price movement with reproducible metrics and promotion gates.
Use this for model quality decisions, not for runtime signal routing.

## Skill dependencies and lifecycle gates
- Start phase: run `parallel-worktree-flow` before starting experiment changes.
- Data-linking phase: co-use with `commodity-news-linking` to ensure canonical entity mapping quality.
- Runtime bridge phase: co-use with `signals-news-bridge-v2` when metrics affect runtime gates.
- Recheck phase: rerun this workflow after label, split, or metric changes.
- Pre-push phase: run required checks from `docs/DEV_WORKFLOW.md`; treat failures as blockers.


## Repository governance baseline (mandatory)
- Follow `docs/workflows/skill-governance-sync.md` for mandatory repository gates (worktree guard, lean loop, plans/memory/handoff, pre-push blockers, repeated-issue escalation).
- Keep this skill focused on domain workflow; do not duplicate repository governance details here.

## Required inputs
- Linked dataset: news item, mapped commodity or instrument, publication timestamp.
- Price series: aligned candles for chosen horizons.
- Model outputs: direction probabilities and impact score.
- Evaluation configuration: horizons, neutral threshold, embargo window.

## Workflow
1. Build evaluation dataset
- Join news items to aligned market data by canonical entity ID and timestamp.
- Drop rows with missing required fields and track exclusion reasons.

2. Label generation
- Define horizons explicitly (for example `1h`, `4h`, `1d`, `5d`).
- Apply neutral band epsilon to avoid labeling market noise as directional.
- Keep both signed return and class label for audit.

3. Leakage controls
- Use chronological splits only.
- Add embargo around split boundaries.
- For hyperparameter search, isolate validation and test windows.

4. Core metrics
- Classification: accuracy, precision, recall, F1 by class and by horizon.
- Calibration: Brier score and reliability bins.
- Coverage: signal rate and abstain or neutral rate.
- Stability: metrics by tag, commodity, and source.

5. Strategy proxy metrics
- Optional, but recommended: run a simple strategy proxy with costs and slippage.
- Report hit rate and drawdown to avoid overfitting to pure classification scores.

6. Promotion gates
- Define explicit pass thresholds by horizon and main commodity groups.
- Block promotion when calibration is unstable or coverage is too low.
- Save full run config and hashes for reproducibility.

7. Tests
- Deterministic fixture tests for label generation.
- Split and embargo tests to prevent leakage regressions.
- Golden report snapshot test for metric schema stability.

## Mandatory pre-push guidance
- Run `python scripts/sync_architecture_map.py --check`.
- Run targeted backtest and metric tests that cover changed horizons or calibration.
- Ensure promotion thresholds and evaluation references remain documented.

## Output checklist
- Dataset and label recipe versioned.
- Leakage-safe split report attached.
- Metrics and calibration report generated.
- Promotion decision documented with pass or fail reasons.

## References
- Read `references/evaluation-checklist.md` before implementing metric changes.
