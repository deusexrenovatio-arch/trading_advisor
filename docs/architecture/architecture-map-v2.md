# Architecture Dependency Map v2 (D3)

## Files
- `docs/architecture/architecture-map-d3.html`
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
2. Use kind/relation filters to isolate slices of architecture.
3. Use presets for common paths:
   - `Trade path`
   - `Research path`
   - `News + Portfolio`
   - `Entity lineage`

## Update workflow
1. Update `docs/architecture/architecture-map-data.js`.
2. Keep source links aligned with:
   - `docs/architecture/layers-v2.md`
   - `docs/architecture/entities-v2.md`
   - `docs/architecture/modules/backend-core.md`
   - `docs/architecture/modules/ui-web.md`
   - `docs/contracts/api-v2.yaml`

