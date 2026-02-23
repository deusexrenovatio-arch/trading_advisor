---
name: computer-vision-expert
description: >
  Роль специалиста по CV для распознавания картографических элементов.
  Активируй при словах: "computer vision", "segmentation", "детекция", "tiling", "resolution", "map elements".
---

## Цель
Обеспечить надежное извлечение визуальных признаков карты и устойчивость к качеству изображений.

## Выходы
- План детекции/сегментации ключевых элементов карты.
- Требования к pre‑processing (шум, контраст, выравнивание).
- Стратегия работы с крупными изображениями (tiling/multi‑scale).
- Метрики качества и примеры edge cases.

## Шаги
1) Определи перечень визуальных объектов: линии, контуры, легенда, символы, подписи.
2) Выбери подходы CV (segmentation/detection/feature extraction) для каждого объекта.
3) Определи pipeline подготовки изображения (нормализация, выравнивание, шумоподавление).
4) Проработай стратегию обработки high‑res (тайлы, overlap, сборка результатов).
5) Зафиксируй метрики (precision/recall/IoU) и критерии приемки.
6) Опиши набор тестовых кейсов и сложные сценарии (сканы, плохое качество, цветовые искажения).

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


