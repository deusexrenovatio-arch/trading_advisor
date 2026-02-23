---
name: data-lineage
description: >
  Регистрация источников данных и lineage: ingestion, pipelines, внешние БД/отчеты/файлы,
  data products и правила качества. Используй при добавлении источника, нового пайплайна,
  маппинга или обновлении data product.
---

# Data Lineage

## Overview
Сделать происхождение данных явным и проверяемым через registry‑as‑code.

## Workflow
1) Зарегистрируй data product в `registry/data-products/*`:
   - owner_module, source, freshness, schema, quality_checks.
2) Свяжи поля объектов с источниками в `registry/objects/*` (fields + source/join).
3) Обнови `registry/modules/*`:
   - зависимости sync/async,
   - события produces/consumes (если ingestion публикует факты).
4) Добавь проверки качества и observability (метрики, логирование, алерты).
5) Добавь тесты:
   - integration‑тесты ingestion,
   - contract‑тесты схем событий (если есть).
6) Прогони `archctl validate` + `archctl policy --from <base> --to <head>`,
   затем обнови docs при необходимости.

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


