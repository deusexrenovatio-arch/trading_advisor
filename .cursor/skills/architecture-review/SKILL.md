---
name: architecture-review
description: >
  Цельный архитектурный аудит приложения или конкретного модуля: bounded contexts,
  направление зависимостей, anti-corruption слои, события/контракты и запрет shared-storage shortcuts.
  Активируй при: "архитектура", "границы модулей", "bounded context", "dependency direction",
  "anti-corruption", "event contracts", "shared DB", "монолитизация gateway".
---

## Цель
Дать целостный архитектурный вывод по приложению (или модулю), а не ограниченный governance-чеклист.

## Режимы ревью
- `app-wide`: полный обход bounded contexts и межконтекстных связей.
- `module-focused`: глубокий аудит одного модуля + его входящих/исходящих контрактов.

## Source of Truth (перед ревью)
1) Архитектурные документы:
- `docs/architecture/architecture-map-v2.md`
- `docs/architecture/layers-v2.md`
- `docs/architecture/entities-v2.md`
- `docs/architecture/modules/*.md`
- `docs/architecture/adr/*.md`
2) Контракты и правила:
- `docs/contracts/api-v2.yaml`
- `contracts/*.json`
- `configs/architecture_policy.yaml`
- `scripts/validate_import_boundaries.py`
- `scripts/validate_api_v2_contract_parity.py`
3) Если `docs/ARCHITECTURE.md` или `module.yaml` отсутствуют, используй перечисленные файлы как фактический SoT и явно фиксируй этот gap в Findings.

## Архитектурные инварианты (обязательная проверка)
1) Bounded contexts
- Контексты разделены по ответственности, нет скрытого смешения доменов в одном модуле.
- Взаимодействие между контекстами идёт через явные контракты/сервисы, а не через прямой доступ к внутренностям.

2) Dependency direction
- Зависимости направлены от orchestration к доменным/infra адаптерам без обратных импортов.
- Нет shortcut-импортов, которые обходят публичные интерфейсы контекста.

3) Anti-corruption layers (ACL)
- Внешние источники/хранилища изолированы в адаптерах/bridge-слоях.
- Доменный код не должен напрямую парсить/читать чужой формат/хранилище.

4) Events and contracts
- Важные события и API-контракты явно описаны и версионированы.
- Любое изменение поведения сопровождается синхронизацией контракта и обработки совместимости.

5) Shared-storage shortcuts
- Запрещён прямой доступ модулей к "чужим" таблицам/файлам/БД в обход репозиториев/bridge.
- Любой общий storage допускается только через явно задокументированный контракт доступа.

6) Gateway/API composition
- API composition не превращается в монолит business-логики.
- Сложная логика выносится в специализированные сервисы/модули с чёткими границами.

## Результат ревью (обязательный формат)
Выдавай строго секциями:
1) `Findings`
- Только реальные проблемы с приоритетом `P0/P1/P2`.
- Для каждой: `причина -> риск -> доказательство (файл:строка) -> рекомендуемый fix`.

2) `Fixes`
- Исправь `P0/P1`, если можно сделать безопасно в текущем контексте.
- Если исправление блокировано средой/данными, зафиксируй blocker и минимальный путь разблокировки.

3) `Residual Risks`
- Что остаётся после фиксов (долги, частичное покрытие, компромиссы).

4) `Next Checks`
- Конкретные проверки/тесты/валидаторы для подтверждения архитектурной целостности.

## Матрица трассируемости (обязательна)
Добавляй матрицу вида:
`requirement/scenario -> bounded context/module -> contract/event -> check/test -> status`.

## Machine-check integration
После существенных правок запускай:
- `python scripts/validate_import_boundaries.py`
- `python scripts/validate_api_v2_contract_parity.py`
- `python scripts/validate_architecture_policy.py`
- `python scripts/run_lean_gate.py`

Если среда блокирует запуск, это не причина пропускать аудит:
- явно фиксируй blocker,
- указывай минимальный путь разблокировки,
- продолжай статический архитектурный анализ.

## Co-use
- Для high-load compute границ: co-use с `minute-candle-performance` после фикса архитектурных границ.
- Для полноты сценариев/приемки/traceability: co-use с `business-analyst`.

## Skill dependencies and lifecycle gates
- Start phase: use this skill at the beginning of the matching task stream.
- Recheck phase: rerun this skill after meaningful fixes or behavior changes in its scope.
- Pre-push phase: run required checks from `docs/DEV_WORKFLOW.md` and treat failures as blockers.

## Repository governance baseline (mandatory)
- Follow `docs/workflows/skill-governance-sync.md` for mandatory repository gates (worktree guard, lean loop, plans/memory/handoff, pre-push blockers, repeated-issue escalation).
- Keep this skill focused on domain workflow; do not duplicate repository governance details here.
