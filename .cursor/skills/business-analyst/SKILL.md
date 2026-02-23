---
name: business-analyst
description: >
  Роль аналитика требований и полноты сценариев.
  Активируй при словах: "requirements", "scope", "use-case", "acceptance", "stakeholder", "traceability".
---

## Цель
Обеспечить полноту требований и соответствие решения бизнес‑сценариям.

## Выходы
- Список user stories и критериев приемки.
- Матрица трассируемости требований → модули пайплайна.
- Выявленные пробелы/риски и список уточнений для стейкхолдеров.
- Приоритизация требований (MVP/next).

## Шаги
1) Собери ключевые сценарии использования и ожидаемые выходы.
2) Зафиксируй критерии успеха (точность, форматы, сроки, интеграции).
3) Построй трассируемость: требование → модуль/шаг пайплайна.
4) Проверь полноту (обязательные элементы карты, масштаб, метаданные).
5) Зафиксируй риски/пробелы и сформулируй вопросы.
6) Согласуй приоритеты и обнови backlog требований.

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


