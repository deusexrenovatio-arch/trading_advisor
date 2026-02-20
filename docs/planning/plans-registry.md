# Plans Registry

`plans/PLANS.yaml` is the machine-readable execution registry for agent-driven work.

## Validation
- Command: `python scripts/validate_plans.py`
- Included in: `python scripts/run_lean_gate.py`

## Schema (v1)
- Top-level:
  - `version` (must be `1`)
  - `updated_at` (ISO date)
  - `items` (non-empty list)
- Item fields:
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
