# CTX-API-UI

## Scope
API handlers, UI behavior, operator actions, and delivery surfaces.

## Owned Paths
- `src/moex_carry/signals_ack.py`
- `src/moex_carry/signals_delivery.py`
- `src/moex_carry/ui/`
- `ui-web/`
- `src/moex_carry/integrations/`

## Guarded Paths (do not change in this context)
- `src/moex_carry/strategy/`
- `src/moex_carry/backtest_v2/`
- `src/moex_carry/storage/`

## Input/Output Contracts
- Input: projections from storage/runtime.
- Output: stable API responses and UI rendering behavior.

## Minimum Checks
- `python scripts/run_lean_gate.py`
- `npm --prefix ui-web run lint`
- `npm --prefix ui-web run build`

