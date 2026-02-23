---
name: testing-suite
description: >
  Навык для генерации и обновления тестов: unit/integration/contract/e2e.
  Активируй при словах: "тест", "покрытие", "pytest", "jest", "contract", "integration", "CI".
---

## Цель
Сделать DoD исполнимым: новые изменения приходят с тестами и проходят CI.

## Выходы
- Unit тесты для domain
- Contract tests для GraphQL/events
- Integration tests для DB/broker/connectors
- Короткий отчёт “что покрыто”
- Обновлённые тест-кейсы и привязка к acceptance сценариям

## Шаги
1) Определи, что изменилось: доменная логика / контракт / интеграция.
2) Зафиксируй тест-кейсы в `docs/test-cases.md` и обнови `configs/acceptance_scenarios.yaml` (test_cases).
3) Unit:
   - happy path + edge cases + invalid inputs
4) Contract:
   - GraphQL schema snapshot/validation
   - event payload schema validation
5) Integration:
   - поднимай зависимости (testcontainers) или моки
6) Проверяй детерминизм: без flaky.
7) В конце: список тестов + команды запуска.

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


