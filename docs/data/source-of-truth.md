# Source of Truth and Projection Rollout

## Scope
This document defines how decision projections are stored and switched during Sprint 3 migration.

## Current state
- Transitional source remains `data/decisions/decision_view.jsonl`.
- Managed DB projection table: `decision_view_projection`.
- New writes are synchronized with write-through (`DecisionLogStore.append` writes JSONL + DB projection upsert).
- API read model:
  - `GET /api/v2/decisions/view`
  - `GET /api/v2/decision-view`

## Feature flag
- `ui.ff_db_projection_source` (`FF_DB_PROJECTION_SOURCE`) controls source selection.
- Behavior:
  - `false` -> read from JSONL (`projection_source=jsonl`)
  - `true` + DB has rows -> read from DB (`projection_source=db`)
  - `true` + DB empty -> fallback to JSONL (`projection_source=jsonl_fallback`)

## Backfill and parity workflow
Historical bootstrap only (for already existing JSONL data):
1. Backfill JSONL into DB projection:
```bash
python scripts/backfill_decision_projection.py \
  --mode backfill \
  --data-dir ./data \
  --db-url sqlite:///./data/moex_carry.db
```
2. Validate parity against source (default threshold `0.995`):
```bash
python scripts/backfill_decision_projection.py \
  --mode parity \
  --data-dir ./data \
  --db-url sqlite:///./data/moex_carry.db \
  --parity-threshold 0.995
```
3. One-shot backfill + parity:
```bash
python scripts/backfill_decision_projection.py --mode all
```

## Parity definition
- Canonical key: `decision_id`.
- Checked fields:
  - `decision_id`
  - `created_at`
  - `strategy_type`
  - `primary_instrument`
  - `action`
  - `risk_state`
  - `news_severity`
- Gate: `parity_ratio >= 0.995`.

## Rollout recommendation
1. Run `--mode all` on historical snapshot.
2. Confirm parity gate pass.
3. Enable `ui.ff_db_projection_source=true` in target environment.
4. Monitor `projection_source` in API responses during canary period.
