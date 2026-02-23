---
name: integration-connector
description: >
  Навык для интеграций с внешними источниками данных (SCADA/PI/OSDU/файлы/API/БД).
  Активируй при: "источник данных", "интеграция", "connector", "ingest", "ETL", "API ключ".
---

## Цель
Сделать интеграцию безопасной, наблюдаемой и совместимой с доменной моделью.

## Выходы
- Registry запись ExternalSource + Connector
- Mapping/normalization rules (в code или config)
- Тесты на ошибки, ретраи, качество данных

## Шаги
1) Зарегистрируй ExternalSource:
   - owner, auth, rate limits, SLA, data classification
2) Спроектируй Connector:
   - режим (batch/stream)
   - ретраи, backoff, DLQ
   - идемпотентность ingest
3) Определи нормализацию:
   - единицы измерения
   - даты/timezone
   - crosswalk external_ids -> canonical IDs (MDM)
4) Определи выход:
   - доменные события или запись в raw zone data platform
5) Безопасность:
   - секреты не хардкодить
   - доступы минимальные
6) Тесты:
   - мок внешнего API
   - негативные кейсы: timeout, quota, invalid payload

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


