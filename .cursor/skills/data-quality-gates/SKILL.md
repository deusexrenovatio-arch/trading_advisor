---
name: data-quality-gates
description: >
  Data quality gates for ingestion and working datasets. Use when adding a new source, dataset, ingestion job,
  crosswalk/entity resolution, reminders about uniqueness/provenance, or "quality checks" / "QC report".
---

# Data Quality Gates

## Goal

Prevent silent data corruption: enforce uniqueness, completeness, and provenance rules.

## Deliverables

* Quality check definitions under `registry/quality/*` (or existing structure).
* Executable QC runner script that outputs `qc_report.json`.
* CI hook (optional but preferred) to run QC on changed pipelines/fixtures.

## Mandatory gates (minimum)

* SourceDocument uniqueness
* Staging record uniqueness (record_type + natural key)
* Crosswalk uniqueness (one active mapping per external key)
* Working facts uniqueness (canonical_id + time + kind)
* Provenance required (source_id + doc/version + ingest_run_id)

## Workflow

1. Define QC checks:

   * SQL assertions for Postgres datasets
   * Cypher assertions for Neo4j links (if needed)
2. Implement runner:

   * outputs PASS/FAIL + counts + sample offending keys (limited).
3. Add fixtures:

   * small representative dataset samples for deterministic tests.
4. Wire into:

   * ingestion scripts (fail fast)
   * CI job for PRs touching ingestion/quality.
5. Document how to interpret QC report.

## Definition of Done

* Breaking QC fails the pipeline before "bad data" reaches working datasets.
* QC report is stored as artifact (file or logs).

## Guardrails

* QC must be deterministic and fast on small fixtures.
* Avoid "warning-only" gates for uniqueness/provenance.

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


