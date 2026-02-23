# CTX-STRATEGY

## Scope
Signal generation, gating, portfolio intent, and decision semantics.

## Owned Paths
- `src/moex_carry/strategy/`
- `src/moex_carry/selection/`
- `src/moex_carry/portfolio/`
- `src/moex_carry/pretrade/`
- `src/moex_carry/domain/`

## Guarded Paths (do not change in this context)
- `src/moex_carry/storage/`
- `contracts/`
- `docs/contracts/`
- `ui-web/`

## Input/Output Contracts
- Input: feature/snapshot data, risk profile, news severity.
- Output: normalized signal payloads and portfolio intent.

## Minimum Checks
- `python scripts/run_lean_gate.py`
- `pytest tests/architecture -q`

