# CTX-DATA

## Scope
Ingestion and normalization of external market/reference data.

## Owned Paths
- `src/moex_carry/data/`
- `src/moex_carry/minute_ingest/`
- `src/moex_carry/history.py`
- `data/output/intraday_minute_series/`
- `data/state/incremental_replay/`

## Guarded Paths (do not change in this context)
- `src/moex_carry/storage/`
- `contracts/`
- `docs/contracts/`
- `ui-web/`

## Input/Output Contracts
- Input: MOEX/CBR adapters and source payloads.
- Output: normalized minute series and incremental ingest state.

## Minimum Checks
- `python scripts/run_loop_gate.py --from-git --git-ref HEAD`
- `python scripts/check_data_integrity.py --data-dir data --max-day-gap 2`


