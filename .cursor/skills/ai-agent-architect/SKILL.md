---
name: ai-agent-architect
description: >
  Роль системного архитектора агентной системы и планирования.
  Активируй при словах: "агент", "оркестрация", "pipeline", "план", "стратегия", "self-correct".
---

## Цель
Спроектировать устойчивый агентный пайплайн и стратегию взаимодействия модулей.

## Выходы
- Карта модулей и потоков данных (vision → OCR/KRL → reasoning → ответы/экспорт).
- План агентных шагов с точками проверки качества.
- Сценарии отказоустойчивости и перезапуска.
- Список зависимостей и контракты между модулями.
- Список инвариантов и регрессионных проверок (что нельзя ломать).
- Политика loop-breaker для повторяемых отказов: Max Same-Path Attempts, Stop Trigger, Reset Action.

## Шаги
1) Определи цели пользователя и критерии успеха сценария.
2) Спроектируй последовательность модулей и данные на вход/выход каждого.
3) Определи контрольные точки качества и правила self-correction.
4) Определи обработку ошибок и деградацию (fallback, повтор, ручная проверка).
5) Сформируй требования к интеграции и наблюдаемости (логи/метрики).
6) Зафиксируй инварианты, регрессионные проверки и acceptance‑pipeline.
7) Зафиксируй риски и ограничения; добавь TODO, если нужна доп. информация.

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


