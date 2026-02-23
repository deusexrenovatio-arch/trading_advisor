---
name: contract-first-graphql
description: >
  Навык для любых задач, где упоминаются GraphQL, схема, типы, резолверы, federation/subgraph,
  или требуется поддержка многих типов консьюмеров через единый контракт.
---

## Цель
Сначала зафиксировать GraphQL контракт (SDL), затем генерировать/обновлять реализацию.

## Входы
- Требование (новый query/mutation/тип/поле)
- Какие клиенты/консьюмеры будут использовать

## Выходы
- Обновлённый `registry/graphql/<module>.graphql`
- (Опц.) контрактные тесты и пример запроса
- Рекомендации по эволюции (breaking/non‑breaking)

## Шаги
1) Опиши изменение в терминах GraphQL:
   - какие типы появляются/меняются
   - какие поля нужны
   - какие аргументы/фильтры
2) Обнови SDL в registry (contract‑first).
3) Проверь совместимость:
   - новое поле -> ок
   - удаление/переименование -> breaking (нужна стратегия версии)
4) Сгенерируй пример query/mutation + ожидаемый shape ответа (как контрактный пример).
5) Только после этого обновляй резолверы/код.

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


