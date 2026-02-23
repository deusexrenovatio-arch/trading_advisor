---
name: openai-ocr-cost-and-reliability-guardrails
description: >
  Guardrails for OpenAI OCR usage: cost control, caching, retries, idempotency, and observability.
  Use when touching OpenAI OCR pipeline, adding OCR features, reducing latency/cost, handling failures, or "quota".
---

# OpenAI OCR Cost & Reliability Guardrails

## Goal

Keep OCR reliable, observable, and affordable.

## Deliverables

* Caching strategy:

  * deterministic request hash (image bytes + params + model version)
  * reuse results when identical
* Retry policy:

  * exponential backoff
  * max attempts
  * classify retryable vs non-retryable errors
* Idempotency:

  * ingest_run_id + document_id + page_index + model version
* Metrics (mandatory):

  * calls_total, failures_total, latency_ms (p50/p95), cost_estimate, cache_hit_rate
* Failure modes:

  * fallback to local OCR if configured (optional)
  * DLQ for failed pages/jobs

## Workflow

1. Define call contract:

   * inputs (image, hints)
   * outputs (text regions + confidence + provenance)
2. Implement caching:

   * store results keyed by hash
3. Implement retries and DLQ:

   * retries for 429/5xx/timeouts
4. Add observability:

   * correlation_id is required in logs
5. Add budget alarms:

   * daily call cap / cost threshold

## Definition of Done

* OCR failures are visible and do not silently corrupt pipeline.
* Identical calls do not cost money twice.
* Cost and latency are measurable.

## Guardrails

* Never log raw images by default.
* Never treat "partial OCR" as success without QC flag.

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


