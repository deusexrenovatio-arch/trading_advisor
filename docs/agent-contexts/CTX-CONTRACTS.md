# CTX-CONTRACTS

## Scope
Schema/version boundaries for storage, decision projection, and public API contracts.

## Owned Paths
- `contracts/`
- `docs/contracts/api-v2.yaml`
- `src/moex_carry/decision_log.py`
- `src/moex_carry/storage/`
- `src/moex_carry/contracts/`

## Guarded Paths (do not change in this context)
- `src/moex_carry/strategy/`
- `src/moex_carry/backtest_v2/`
- `ui-web/`

## Input/Output Contracts
- Input: contract evolution requests.
- Output: backward-compatible schema/API/storage contract updates.

## Risk Level
High. If combined with any other context, split into ordered patches:
1. contract changes
2. implementation changes
3. docs and follow-up checks

## Minimum Checks
- `python scripts/run_loop_gate.py --from-git --git-ref HEAD`
- `python scripts/validate_dependency_decisions.py`
- `python scripts/validate_codeowners.py`


