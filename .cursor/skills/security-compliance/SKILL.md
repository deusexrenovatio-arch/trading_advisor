---
name: security-compliance
description: >
  Навык для требований безопасности и комплаенса (в т.ч. HSE/ESG отчётность, доступы, аудит).
  Активируй при: "секреты", "PII", "роль", "доступ", "audit", "compliance", "HSE", "ESG".
---

## Цель
Не допустить регрессий безопасности и обеспечить аудитируемость.

## Выходы
- Checklist security
- Правки в конфиге/коде (если нужно)
- Записи классификации данных в registry

## Шаги
1) Классифицируй данные:
   - PII/financial/regulatory/safety
2) Проверь секреты:
   - env/secret manager, никаких ключей в коде
3) Доступы:
   - least privilege
   - audit trail на изменения критичных сущностей (accounting, permits, HSE)
4) Валидация входа:
   - schema validation
5) Добавь security tests где уместно.

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


