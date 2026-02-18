---
name: signals-news-bridge-v2
description: Link news_impact events to runtime signal lifecycle and decision/execution audit references in API v2. Use when changing /api/v2/signals/*, /api/v2/news/feed, decision projection fields, or news/risk gating behavior.
---

# Signals News Bridge v2

## Purpose
Create a deterministic bridge between news impact events and signals.
Use this skill for online signal explainability and audit linkage, not just offline model scoring.

## Skill dependencies and lifecycle gates
- Start phase: run `parallel-worktree-flow` before runtime/API changes.
- Linking phase: co-use with `commodity-news-linking` for canonical entity references.
- Evaluation phase: co-use with `news-impact-backtest-lab` for calibration and leakage-safe validation.
- API phase: update contracts first, then implementation and tests.
- Pre-push phase: run required checks from `docs/DEV_WORKFLOW.md`; treat failures as blockers.

## Non-goals
- Do not tune NLP models here.
- Do not replace backtest labeling workflows. Use `news-impact-backtest-lab` for that.

## Required inputs
- Active signals: `signal_id`, entity refs, lifecycle state, action.
- News impacts: `news_event_id`, `severity`, `impact_score`, `direction`, `published_at`, entity or commodity refs.
- Decision linkage: `decision_id`, action and execution refs.
- Gate configuration: lookback window and severity thresholds.

## Workflow
1. Contract first
- Update contracts before code paths.
- Keep v1 adapter compatibility if v2 fields are added.

2. Define linkage semantics
- `used_in_decision`: event was inside decision lookback and affected gate or action.
- `posthoc_label`: event attached only for evaluation or backtest.
- Persist both types explicitly, do not mix them.

3. Runtime linking
- Filter news by entity or commodity and time window.
- Apply deterministic thresholds from `news-geopolitics-filter`.
- Derive `news_gate_action`: `block`, `reduce`, or `allow`.
- Attach matched event IDs and severity summary to signal and decision payloads.

4. Projection and API
- In `/api/v2/signals/active`, expose compact bridge fields such as:
  - `news_gate_action`
  - `news_severity`
  - `matched_news_event_ids`
- In `/api/v2/news/feed`, expose `decision_ref` and optional `signal_refs`.
- Keep detailed links in detail endpoints and storage, not in table-heavy summaries.

5. Idempotency and replay safety
- Build stable link IDs from (`news_event_id`, `signal_id`, `link_type`, `window_start`).
- Use upsert semantics for replays and backfills.
- Track producer source: `runtime`, `backfill`, or `backtest`.

6. Test coverage
- Unit: gate action derivation and link-type assignment.
- API: signal and news endpoints expose consistent references.
- Replay regression: duplicate processing does not duplicate links.

## Why this skill exists
Backtests answer "did news predict price direction after the fact".
This bridge answers "which news affected this signal right now" for gating, explainability, and audit.

## Output checklist
- Contracts updated first.
- Link model and idempotency rules implemented.
- Signal and news endpoints expose bridge references.
- Tests pass for runtime and replay flows.

## Mandatory pre-push guidance
- Run `python scripts/sync_architecture_map.py --check`.
- Run targeted tests for signal/news endpoints and replay idempotency.
- Keep API docs and acceptance scenarios aligned with bridge fields.

## References
- Read `references/link-payloads.md` for minimal payload contract examples.
