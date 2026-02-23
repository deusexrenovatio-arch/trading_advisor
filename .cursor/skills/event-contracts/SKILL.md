---
name: event-contracts
description: >
  Навык для добавления/изменения доменных событий (event bus): topic/event name, schema, version,
  producer/consumer, outbox, idempotency, DLQ.
---

## Цель
Сделать события “первоклассными контрактами”: с версионированием, схемой и тестами.

## Выходы
- `registry/events/<eventName>/schema.json`
- Обновление `module.yaml` (produces/consumes)
- Рекомендованные тесты: publish/consume + idempotency

## Шаги
1) Проверь naming: `<domain>.<aggregate>.<event>.v<major>`.
2) Определи payload как минимальный набор фактов:
   - обязательные поля: event_id, occurred_at, schema_version, correlation_id, idempotency_key, object references
3) Оформи JSONSchema (или Avro/Proto) и зарегистрируй в registry.
4) Укажи producer и consumers (модули) в registry.
5) Проверь правила эволюции:
   - добавление optional -> ok
   - удаление/смена типа -> новая major версия
6) Проверь технические паттерны:
   - outbox у producer
   - idempotency у consumer
   - DLQ + retry policy
7) Сгенерируй contract tests (минимум: schema validation + duplicate delivery).

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


