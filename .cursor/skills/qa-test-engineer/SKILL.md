---
name: qa-test-engineer
description: >
  Роль QA инженера для сквозной проверки качества и регрессий.
  Активируй при словах: "QA", "test plan", "acceptance", "regression", "validation".
---

## Цель
Гарантировать качество модулей и end‑to‑end пайплайна перед релизом.

## Выходы
- План тестирования (unit/integration/system/UAT).
- Набор контрольных карт и ожидаемые результаты.
- Матрица проверок по модулям и интерфейсам.
- Список выявленных дефектов/рисков и критерии приемки.
- Acceptance checklist и результаты регрессионного прогона.
- Обновлённые тест-кейсы и привязка к acceptance сценариям.

## Шаги
1) Определи тестовые сценарии по ключевым типам карт.
2) Сформируй ожидаемые результаты и критерии pass/fail.
3) Зафиксируй тест-кейсы в `docs/test-cases.md`.
4) Обнови acceptance чек-лист в `configs/acceptance_scenarios.yaml` и привяжи test_cases.
5) Настрой регрессионный набор и автоматизацию.
6) Проверь негативные/краевые сценарии (плохое качество, шум, неполные данные).
7) Добавь UI/API smoke-check для ключевых пользовательских потоков.
8) Сформируй отчеты по качеству, список регрессий и рекомендации.
9) Зафиксируй блокеры релиза и условия допуска.

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


