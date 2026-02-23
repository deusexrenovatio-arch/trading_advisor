---
name: composition-contracts
description: >
  Контракты композиции GraphQL: field-level ownership, resolver mapping, joins, кеширование, auth, SLO.
  Используй при добавлении/изменении GraphQL полей, составных запросов, дашбордов,
  федерации/композиции подграфов или маппинге резолверов.
---

# Composition Contracts

## Overview
Зафиксировать, кто владеет каждым полем, откуда оно берется, и как собирается ответ в GraphQL.

## Workflow
1) Обнови registry:
   - `registry/objects/*`: fields + owner/join/freshness.
   - `registry/resolvers/*`: owner_module, resolver_type, join key, cache, auth, latency.
   - `registry/modules/*`: dependencies sync/async при новых связях.
2) Обнови GraphQL SDL в `registry/graphql/*`.
3) Реализуй резолверы:
   - batching/DataLoader, таймауты, лимиты сложности, прокидывание `as_of`.
4) Добавь тесты:
   - contract snapshot для SDL,
   - integration‑тесты композиции.
5) Прогони `archctl validate` + `archctl policy --from <base> --to <head>`.
6) Обнови `docs/ARCHITECTURE.md`, если меняется модель композиции.

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


