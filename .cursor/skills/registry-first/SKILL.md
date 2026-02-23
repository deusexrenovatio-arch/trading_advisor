---
name: registry-first
description: >
  Обязательный навык для любых изменений, затрагивающих данные/контракты/события/модули.
  Активируй, если в задаче есть: "schema", "contract", "GraphQL", "event", "topic", "новый модуль",
  "интеграция", "объект", "реестр", "каталог", "data product", "источник данных".
---

## Цель
Сделать так, чтобы любое изменение начиналось с обновления `/registry/**` и было **машинно‑проверяемым**.

## Входы
- Описание изменения (что добавляем/меняем)
- Целевые модули/объекты/события (если известны)

## Выходы (артефакты)
- Обновлённые файлы в `/registry/**`:
  - `registry/modules/<module>/module.yaml`
  - `registry/objects/*.yaml`
  - `registry/events/<event>/schema.json`
  - `registry/graphql/<module>.graphql`
- Обновлённые автогенерируемые docs (если настроено)
- Прогон `archctl validate` (или эквивалент)

## Пошаговый алгоритм
1) Классифицируй изменение: Module / ObjectType / EventType / GraphQL / Integration / Contract.
2) Добавь или обнови registry‑артефакты (минимально необходимый набор).
3) Если событие новое/изменилось:
   - проверь версионирование (`…v1`, `…v2`)
   - добавь schema и отметь producer/consumers
4) Если меняется GraphQL:
   - обнови subgraph SDL в `registry/graphql/*`
5) Если registry отсутствует — обнови `/contracts/**` и docs как source of truth.
6) Запусти `archctl validate` (или добавь TODO, если команды ещё нет).
7) Сгенерируй impact‑summary: какие модули затронуты, что breaking.

## Запреты
- Нельзя начинать менять код, пока registry не обновлён.
- Нельзя добавлять publish/subscribe на событие без registry записи.
- Нельзя менять контрактные поля без фиксации версии и обратной совместимости.

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


