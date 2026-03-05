# Session Handoff
Updated: 2026-03-06 06:10 UTC

## Goal
- Shift Telegram/news flow from fact-only market commentary to commodity-specific fundamental causes that are later verified by realized price move on 1H and 1D horizons.

## Task Request Contract
- Objective: implement event-first root-cause extraction with a commodity dependency graph (exporters, producers, importers, chokepoints, transmission links) so primary triggers are detected before financial recaps.
- In Scope: wide per-commodity classification dictionaries, directed geographic/dependency graph, event-first causal inference integration in `news_causal`, and query expansion to fetch root-cause sources.
- Out of Scope: replacing upstream providers, introducing LLM-only extraction as the primary path, and changing trading execution policy outside current signal/news bridge.
- Constraints: preserve current runtime stability and API compatibility, keep deterministic fallbacks for low-confidence items, and require leakage-safe evaluation logic.
- Done Evidence: passing `python scripts/validate_task_request_contract.py`, pre/post `python scripts/run_lean_gate.py`, targeted tests for new causal tagging and 1H/1D verification logic, and generated artifacts showing filtered cause-first rows plus verification metrics.
- Priority Rule: prioritize precision of fundamental-cause alerts over coverage; when in doubt classify as uncertain/noise rather than promote to Telegram.

## Current Delta
- Added `news_commodity_graph.py` with wide per-commodity role catalogs: exporters, producers, importers, chokepoints.
- Added directed dependency edges per commodity (geo/transmission graph) and route resolver to commodity node.
- Added event-first causal inference (`chokepoint`, `outage/restart`, `export controls`, `demand shifts`, weather).
- `news_causal.py` now uses hybrid scoring: taxonomy rules + graph event-first candidates with source priority.
- Causal payload now carries `cause_route_key`, `cause_claim_status`, and matched `cause_entities`.
- `news_scores` schema/runtime persist these fields and legacy backfill updates old rows on ingest cycle.
- Ingestion queries are now auto-augmented with event-first terms to fetch root-cause sources beyond finance recaps.
- Feed/Telegram formatting includes claim status, route, and entities; new tests cover graph and query expansion.

## First-Time-Right Report
1. Confirmed coverage: taxonomy, clustering, and verification gates are included for both ingestion-time labeling and feed-time prioritization.
2. Missing or risky scenarios: conflicting headlines, delayed reactions beyond 1D, and supply-chain events with cross-commodity spillover may reduce deterministic confidence.
3. Resource/time risks and chosen controls: potential backfill cost managed via smoke-first windows, strict horizon metrics (1H/1D), and deterministic fallbacks before broad rollout.
4. Highest-priority fixes or follow-ups: enforce cause/effect gate before Telegram feed export, then calibrate thresholds against realized move distributions by commodity.

## Repetition Control
- Max Same-Path Attempts: 2
- Stop Trigger: two consecutive attempts fail to improve precision on causal validation metrics (or fail deterministic gate tests) for the same rule path.
- Reset Action: freeze current rule branch, snapshot false-positive/false-negative slices, and restart from commodity-specific hypothesis set with tightened source and mechanism constraints.
- New Search Space: (1) mechanism-first taxonomy rules, (2) source reliability + novelty gating, (3) event-to-price alignment window adjustments for 1H/1D verification.
- Next Probe: run a focused historical sample for one commodity bucket (energy/metals/agri) and compare precision/coverage before and after causal gates.

## Blockers
- No blockers.

## Next Step
- Backfill `news_shock_rows` farther back in time to increase verified 1H/1D sample size for non-BRN commodities.

## Validation
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/run_lean_gate.py`
