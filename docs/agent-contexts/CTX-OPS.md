# CTX-OPS

## Scope
Governance automation, observability, and operational workflow tooling.

## Owned Paths
- `src/moex_carry/observability/`
- `scripts/`
- `docs/workflows/`
- `docs/runbooks/`
- `.githooks/`

## Guarded Paths (do not change in this context)
- `src/moex_carry/strategy/`
- `src/moex_carry/backtest_v2/`
- `ui-web/`
- `contracts/`

## Input/Output Contracts
- Input: process/governance requirements.
- Output: deterministic checks, automation scripts, and runbook behavior.

## Minimum Checks
- `python scripts/run_lean_gate.py`
- `python scripts/validate_session_handoff.py`

