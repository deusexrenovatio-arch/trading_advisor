---
name: docs-sync
description: >
  Навык для обновления документации и диаграмм из registry (docs-as-code).
  Активируй при: "обнови документацию", "diagram", "mermaid", "архитектура.md",
  или когда меняются registry/contracts.
---

## Цель
Документация всегда соответствует реальности: генерируется из registry.

## Выходы
- Обновлённые `/docs/generated/*`
- Обновлённые диаграммы (Mermaid) в `/docs/ARCHITECTURE.md` или generated секциях
- Обновлённые ключевые архитектурные страницы (если генерация не настроена)

## Шаги
1) Прогони `archctl graph --format mermaid` для ключевых доменов/модулей.
2) Обнови generated‑секции (между маркерами BEGIN/END).
3) Если archctl/registry не настроены — обнови docs вручную (архитектура, data‑sources, contracts).
4) Проверь, что docs закоммичены в PR.
5) Для governance-изменений проверь синхронность артефактов:
   - `docs/DEV_WORKFLOW.md`
   - `docs/session_handoff.md`
   - `docs/runbooks/governance-remediation.md`
   - `configs/agent_incident_policy.yaml`

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


