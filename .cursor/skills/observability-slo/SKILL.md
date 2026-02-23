---
name: observability-slo
description: >
  Навык для добавления наблюдаемости: метрики, логи, трейсы, health/readiness, SLO.
  Активируй при: "мониторинг", "SLO", "метрики", "алерты", "tracing", "healthcheck".
---

## Цель
Любой модуль должен быть операционно управляем: измеряем, алертим, дебажим.

## Выходы
- Список обязательных метрик и лог‑полей
- Обновление manifest (`slo`, `tier`)
- Runbook (кратко)

## Шаги
1) Для новых endpoint/event consumer добавь:
   - latency, error rate, throughput
   - consumer lag (для очередей)
2) Логи:
   - correlation_id, module_id, object references (well_id/asset_id)
3) Трейсинг:
   - propagate correlation_id через GraphQL → events
4) Health:
   - liveness/readiness
5) Runbook:
   - топ‑5 частых проблем и куда смотреть

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


