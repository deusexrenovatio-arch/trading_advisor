---
name: commodity-news-linking
description: Deterministic workflow for linking raw news to canonical commodity, instrument, and ticker entities with multi-label tags and confidence. Use when implementing or changing news classification and entity mapping.
---

# Commodity News Linking

## Purpose
Map each news item to canonical market entities and taxonomy tags with reproducible rules.
Use this before impact scoring, news gates, and signal enrichment.

## Skill dependencies and lifecycle gates
- Start phase: run `parallel-worktree-flow` before changes in a feature worktree.
- Mapping design phase: apply this skill when updating deterministic rules and crosswalk logic.
- Integration phase: co-use with `signals-news-bridge-v2` when links are exposed in signal APIs.
- Evaluation phase: co-use with `news-impact-backtest-lab` for leakage-safe validation.
- Pre-push phase: run required checks from `docs/DEV_WORKFLOW.md`; treat failures as blockers.


## Repository governance baseline (mandatory)
- Follow `docs/workflows/skill-governance-sync.md` for mandatory repository gates (worktree guard, lean loop, plans/memory/handoff, pre-push blockers, repeated-issue escalation).
- Keep this skill focused on domain workflow; do not duplicate repository governance details here.

## Required inputs
- News payload: `title`, `content` or `summary`, `source`, `published_at`, `language`.
- Canonical dictionaries: commodity codes, ticker aliases, issuer aliases, tag taxonomy.
- Optional semantic model output for fallback scoring.

## Workflow
1. Canonical IDs first
- Use stable IDs for commodities and instruments.
- Keep source aliases in crosswalk tables, not in business logic branches.

2. Multi-stage linking order
- Stage A: deterministic dictionary and ticker matches.
- Stage B: context rules (country, producer orgs, sector terms, sanctions, weather markers).
- Stage C: semantic fallback only if A and B are inconclusive.

3. Multi-label assignment
- Produce ranked candidates with scores.
- Keep one `primary_commodity_id` plus optional secondary links.
- Do not drop ambiguous items. Route uncertain cases to `UNKNOWN` with reasons.

4. Tag assignment
- Assign tags from a fixed taxonomy (for example `SUP_INC`, `SUP_DEC`, `DEM_INC`, `DEM_DEC`, `GEO_POL`).
- Allow multiple tags when evidence supports more than one.
- Store rationale fields (`matched_rules`, key phrases, optional model score).

5. Quality gates
- Minimum deterministic coverage threshold for high-volume commodities.
- Unknown rate and class-balance drift must be tracked.
- Enforce language and timestamp validity.

6. Storage outputs
- Save canonical links separately from raw source payload.
- Keep full provenance: source item ID, mapping stage, confidence, model version.

7. Tests
- Dictionary and alias mapping unit tests.
- Ambiguous and multilingual fixture tests.
- Regression tests for stable mappings on known headlines.

## Mandatory pre-push guidance
- Run `python scripts/sync_architecture_map.py --check`.
- Run targeted tests for updated mapping logic and API projections.
- If contracts change, update docs and keep `AGENTS.md` skill registry in sync.

## Output checklist
- Crosswalk rules updated and versioned.
- Primary and secondary entity links emitted.
- Unknown and ambiguous paths handled explicitly.
- Mapping tests and drift checks updated.

## References
- Read `references/linking-rules-template.md` for template payloads and score structure.
