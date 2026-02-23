---
name: architecture-review
description: >
  Архитектурный ревью изменений: границы модулей, зависимости, события, отсутствие shared DB.
  Активируй при: "архитектура", "микросервис", "границы модулей", "рефакторинг домена",
  "GraphQL federation", "event-driven". For high-load compute boundary changes, co-use with minute-candle-performance.
---

## Цель
Поймать архитектурные ошибки до merge: неправильные зависимости, нарушение bounded contexts.

## Шаги
1) Прочитай `/docs/ARCHITECTURE.md` и релевантные `module.yaml`.
2) Проверь:
   - нет прямого доступа к чужим хранилищам
   - синхронные зависимости минимальны и оправданы
   - события описаны и версионированы
   - изменения не превращают GraphQL gateway в “монолит резолверов”
3) Если видишь нарушение — предложи альтернативу:
   - вынести в новый модуль
   - заменить sync на async event
   - добавить data product вместо “чужих запросов”
4) Сформируй список P0/P1 проблем и рекомендации.

## Co-use with minute-candle-performance
- Use `minute-candle-performance` together with this skill when architecture changes affect high-load compute paths (minute replay, batch scoring, HPO runtime).
- Apply in order:
  1) `architecture-review`: approve module boundaries and dependency direction.
  2) `minute-candle-performance`: choose numeric stack and optimize kernels/orchestration inside approved boundaries.
- Reject changes that mix boundary violations with performance optimizations in one undecoupled step.



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


