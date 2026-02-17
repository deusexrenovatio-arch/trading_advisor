# Architecture Dependency Map v2 (D3)

## Files
- `docs/architecture/architecture-map-d3.html`
- `docs/architecture/architecture-map-data.json` (source of truth)
- `docs/architecture/architecture-map-data.js`

## What is covered
- **Layers**: L1..L6 from `docs/architecture/layers-v2.md`.
- **Backend modules**: analytics, signal/decision, research, news, portfolio, execution/audit.
- **Public API surface**: `/api/v2/*` + legacy v1 adapter bridge.
- **Workspaces**: Trade Console, Decision Audit, Research Lab, News Intelligence, Portfolio Control.
- **Canonical entities**: Issuer/Asset/Instrument/Pair + Signal/Decision/Execution + Research + Portfolio entities.
- **Storages**: SQLite tables, JSONL projections, runtime files, observability counters.
- **External systems**: MOEX ISS, CBR, news providers, Telegram, operator.

## How to view
1. Open `docs/architecture/architecture-map-d3.html` in a browser.
2. Start with `View: Clean overview` + `Preset: Core flow (clean default)`.
3. Switch to `View: Full dependency graph` only for deep dependency audits.
4. Use kind/relation filters to isolate slices of architecture.
5. Use presets for common paths:
   - `Core flow (clean default)`
   - `Trade path`
   - `Research path`
   - `News + Portfolio`
   - `Entity lineage`
6. In full mode, label density auto-reduces for readability; click a node to focus local neighborhood.

## Update workflow
1. Update `docs/architecture/architecture-map-data.json`.
2. Run `python scripts/sync_architecture_map.py`.
3. Verify consistency gate: `python scripts/sync_architecture_map.py --check`.
4. Do not edit `architecture-map-data.js` manually (generated file).
5. Keep source links aligned with:
   - `docs/architecture/layers-v2.md`
   - `docs/architecture/entities-v2.md`
   - `docs/architecture/modules/backend-core.md`
   - `docs/architecture/modules/ui-web.md`
   - `docs/contracts/api-v2.yaml`
6. For workflow/skill/process-doc updates (without module/API/entity changes), run only `python scripts/sync_architecture_map.py --check`; map data regeneration is not required.
