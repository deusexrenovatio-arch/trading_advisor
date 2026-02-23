---
name: source-onboarding
description: >
  Онбординг нового источника данных (PDF/таблицы/API) с обязательными uniqueness‑гейтами,
  entity resolution + crosswalk и построением working datasets, которые ссылаются на
  canonical сущности, а не на исходные документы. Используй при задачах ingestion/
  источники/отчеты/парсер/сопоставление сущностей/working report/витрина/MDM.
---

## Цель
Сделать источник управляемым: registry‑first, уникальность, canonical linking, provenance.

## Порядок работ (обязательный)
1) Обнови registry‑as‑code до кода:
   - `registry/sources/*.yaml`
   - `registry/datasets/*.yaml`
   - `registry/quality/*.yaml`
   - `registry/policies/*.yaml`
2) Зафиксируй strong keys и правила нормализации.
3) Опиши crosswalk и историю маппинга (valid_from/valid_to).
4) Определи working dataset с **canonical IDs only** и provenance required.
5) Прогони `archctl validate`.
6) Только затем реализуй ingestion/резолвинг/апдейтеры.

## Обязательные гейты
- SourceDocument uniqueness
- Staging uniqueness (record_type + source_natural_key)
- Crosswalk uniqueness (one active mapping)
- Working fact uniqueness
- Provenance required

## Запреты
- Нельзя использовать SourceDocument как join‑ключ в working reports.
- Нельзя писать парсер с доменной логикой (это в core/resolution).
- Нельзя пропускать ручной разбор конфликтов при неоднозначных матчах.

## Минимальные тесты
- Unit: нормализация ключей, dedupe
- Integration: ingest → staging → resolution → working facts
- Contract: schema совместимость рабочих фактов

## Финальный отчет
Перечисли:
- какие registry файлы изменены
- какие uniqueness gates настроены
- какие canonical сущности и ключи используются
- как устроен provenance
- какие тесты добавлены

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


