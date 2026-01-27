# UI UX Standards (Field & Param Metadata)

## Purpose
- Keep UI outputs human-friendly and consistent across tabs.
- Avoid raw technical keys in user-facing screens.

## Field outputs (tables, detail panels, chips)
- Single source of truth: `ui-web/src/App.tsx` -> `fieldMeta` + `formatValue` + `getFieldLabel/getFieldTooltip`.
- Formatting rules:
  - `percent`/`bps`/`currency`/`days` via `FieldMeta.format`.
  - Fallback digits via `columnDigits`.
- Tooltips:
  - Use formula + interpretation ("Формула: ... Интерпретация: ...").
- Null/empty values:
  - Display `—` (dash) for missing values.
  - Boolean -> "Да/Нет".
- Deduplication:
  - Detail panels should avoid repeating table fields (see `stripDuplicates`).

## Backtest v2 parameters
- Single source of truth: `paramMeta` in `ui-web/src/App.tsx`.
- Label + tooltip:
  - Always show human-readable labels (no raw keys like `strategy.z_window`).
  - Tooltips use formula + interpretation.
- Dict parameters:
  - Render as labeled rows (e.g., allocation weights per basket).
  - Inputs are numeric and stored as structured objects.
- Filtering:
  - Param filter matches both key and label.
- Section ordering:
  - Use `paramSectionOrder` (Test/Universe/Execution/Rates/Costs/Liquidity/Strategy/Portfolio/Allocation/Rebalance).

## Tests and acceptance
- UI test coverage: `ui-web/tests/backtest-forward-hpo.spec.ts` includes label + dict checks.
- Manual test cases: `docs/test-cases.md` -> TC-BACK-V2-UI-002.
- Acceptance mapping: `configs/acceptance_scenarios.yaml` -> frontend-params-specs.

## Release notes
- Record UI metadata changes in `docs/release-notes.md`.
