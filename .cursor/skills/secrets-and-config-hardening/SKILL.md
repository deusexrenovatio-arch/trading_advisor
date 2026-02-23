---
name: secrets-and-config-hardening
description: >
  Secrets handling and configuration hardening. Use when dealing with API keys (OpenAI), env vars,
  config files, logging of sensitive data, secret scanning, .env templates, or "do not hardcode secrets".
---

# Secrets & Config Hardening

## Goal

Stop accidental leaks and make configuration explicit and safe.

## Deliverables

* `.env.example` (or `config/*.env.example`) with required variables and comments.
* Config schema validation (runtime check) for required env vars.
* Secret scanning setup recommendation (gitleaks or similar).
* Logging rules for sensitive payloads.

## Workflow

1. Inventory secrets:

   * OpenAI keys, DB creds, tokens.
2. Ensure secrets are not in code:

   * move to env / secret manager.
3. Add config validation at startup:

   * fail fast if required vars missing.
4. Add redaction:

   * do not log OCR raw text/images unless explicitly allowed.
5. Add scanning guidance:

   * pre-commit or CI secret scan.

## Definition of Done

* Repo contains no secrets.
* Services fail fast with clear config errors.
* Logs do not include sensitive payloads by default.

## Guardrails

* Avoid "optional" secrets that cause silent degraded behavior without warning.
* Prefer explicit feature flags for external AI calls.

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


