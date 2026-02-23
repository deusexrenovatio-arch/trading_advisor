---
name: module-scaffold
description: >
  Навык для создания нового доменного модуля или коннектора.
  Активируй при фразах: "создай модуль", "новый сервис", "bounded context", "connector", "ingestion".
---

## Цель
Создать модуль по единому шаблону: manifest + контракты + тестовые заготовки.

## Выходы
- Структура каталога сервиса
- `registry/modules/<module>/module.yaml`
- `registry/graphql/<module>.graphql` (stub)
- (если нужно) базовые события в `registry/events/*`
- заготовки тестов и observability

## Шаги
1) Определи тип: service / connector / job / library.
2) Создай `module.yaml`:
   - domain, owner_team, tier
   - objects owned
   - events produces/consumes
   - dependencies sync/async
   - stage_tags (0–7)
3) Создай subgraph SDL (минимально: Query { _health } + базовые типы).
4) Скелет кода по структуре:
   - domain/ application/ adapters/ infra/
5) Добавь базовые проверки:
   - health/readiness
   - structured logging + correlation_id
6) Создай тестовые заглушки:
   - unit (domain invariants)
   - contract (GraphQL schema snapshot)

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


