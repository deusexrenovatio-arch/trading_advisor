# Plans Registry

`plans/items/` is the canonical file-per-item execution registry for agent-driven work.
`plans/PLANS.yaml` is a generated compatibility output.

## Validation
- Command: `python scripts/validate_plans.py`
- Sync command: `python scripts/sync_state_layout.py`
- Included in:
  - `python scripts/run_loop_gate.py`
  - `python scripts/run_pr_gate.py`

## Schema (v1)
- Index top-level (`plans/items/index.yaml`):
  - `version` (must be `1`)
  - `updated_at` (ISO date)
  - `items` (non-empty list of `id` + `path`)
- Item file fields:
  - `id` (unique, uppercase/digits/hyphen)
  - `title`
  - `lane`
  - `status` (`planned|active|blocked|completed|deferred`)
  - `execution_mode` (`autonomous|assisted|manual`)
  - `owner`
  - `acceptance` (non-empty list)
  - `checks` (non-empty list)
  - `dependencies` (optional list of known item ids)
  - `started_at` / `completed_at` (optional ISO dates)

## Invariants
- At most one `active` item per `lane`.
- `completed` items must include `completed_at`.
- Dependencies must reference known plan item ids.
