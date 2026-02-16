# Worktree Governance

## Active topology
- `d:/New Project` -> `main` (baseline and release prep)
- `d:/wt-refactor` -> `refactor/app-core` (contracts/core entities)
- `d:/wt-signals-backtest` -> `chat/signals-backtest-lab` (research/performance)
- `d:/wt-bot` -> `feat/bot-integration` (ACK/actions integration)
- `d:/wt-integration` -> `chore/integration-sync` (conflict detection and smoke checks)

## Daily routine
1. `git fetch origin`
2. `git rebase origin/main` in each active feature worktree.
3. Run targeted stream tests.
4. Push feature branch with `--force-with-lease` only for owned feature branches.
5. Sync integration branch with no-ff merges for early conflict detection.

## Merge order policy
1. `refactor/app-core`
2. `chat/signals-backtest-lab`
3. `feat/bot-integration`
4. docs/release branch updates

## Branch ownership matrix
- `refactor/app-core`: domain contracts, v2 schemas, adapter surfaces.
- `chat/signals-backtest-lab`: minute replay canon, compute stack policy, HPO quality gates.
- `feat/bot-integration`: Telegram ACK and action ingestion.
- `chore/integration-sync`: integration-only conflict fixes and smoke verification.

## Integration gate
- Required before merge to `main`:
  - API smoke for `/api/*` and `/api/v2/*`
  - `pytest -q tests/test_ui_api.py tests/test_signal_api.py`
  - Research subset: `pytest -q tests/hpo tests/backtest_v2`
