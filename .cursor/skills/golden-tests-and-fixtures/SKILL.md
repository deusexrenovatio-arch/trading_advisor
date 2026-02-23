---
name: golden-tests-and-fixtures
description: >
  Golden tests for AI/CV/OCR/data pipelines. Use when adding/refactoring parsers, OCR, contour extraction,
  label linking, exports, or when you need regression protection with fixtures and expected outputs.
---

# Golden Tests & Fixtures

## Goal

Lock behavior with known inputs/outputs so AI-driven refactors do not silently change results.

## Deliverables

* `fixtures/` folder (or `testdata/`) with:

  * sample inputs (images/PDF snippets/GeoJSON/JSONL)
  * expected outputs (result.json, qc_report.json, overlays if needed)
* A golden test runner:

  * compares outputs to expected with tolerances
  * produces diff summary

## Workflow

1. Select fixtures:

   * cover "easy", "typical", and "nasty" cases (noise, rotated text, dashed lines).
2. Define expected outputs:

   * stable, minimal, versioned.
3. Comparison strategy:

   * exact match for IDs, schema, key fields
   * tolerance for floats/geometry (eps, rounding)
4. Add tests:

   * Python: pytest
   * Node: node --test
5. Gate:

   * PR touching pipeline code must update fixtures intentionally.

## Definition of Done

* A pipeline refactor cannot change outputs without updating expected fixtures.
* Diff report makes changes explainable.

## Guardrails

* Keep fixtures small (fast tests).
* Do not store huge binaries in repo; use downsampled representative cases.

## Skill dependencies and lifecycle gates
- Start phase: use this skill at the beginning of the matching task stream.
- Recheck phase: rerun this skill after meaningful fixes or behavior changes in its scope.
- Pre-push phase: run required checks from `docs/DEV_WORKFLOW.md` and treat failures as blockers.

## Repository governance baseline (mandatory)
- Follow `docs/workflows/skill-governance-sync.md` for mandatory repository gates (worktree guard, lean loop, plans/memory/handoff, pre-push blockers, repeated-issue escalation).
- Keep this skill focused on domain workflow; do not duplicate repository governance details here.
## Mandatory pre-push guidance
- Run `python scripts/sync_architecture_map.py --check` when boundaries or integrations are touched.
- Run required checks from `docs/DEV_WORKFLOW.md` for touched areas; treat failures as blockers.
- If contracts/registry/docs changed, update source-of-truth artifacts before push and keep notes in AGENTS or PR summary.


