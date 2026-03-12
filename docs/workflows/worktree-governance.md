# Worktree Governance

## Active topology
- `d:/New Project` -> `main` (baseline and release prep)
- `d:/wt-refactor` -> `refactor/app-core` (contracts/core entities)
- `d:/wt-signals-backtest` -> `chat/signals-backtest-lab` (research/performance)
- `d:/wt-bot` -> `feat/bot-integration` (ACK/actions integration)
- `d:/wt-integration` -> `chore/integration-sync` (conflict detection and smoke checks)

## Dev ports policy
- Reserved for `main` worktree:
  - Backend API: `8050`
  - Frontend Vite: `5176`
- Feature worktrees must use dedicated ports (example baseline):
  - `d:/wt-refactor`: backend `8061`, frontend `5186`
  - `d:/wt-signals-backtest`: backend `8062`, frontend `5187`
  - `d:/wt-bot`: backend `8063`, frontend `5188`
  - `d:/wt-integration`: backend `8064`, frontend `5189`
- Frontend proxy override for worktrees:
  - Use `VITE_API_PROXY_TARGET=http://127.0.0.1:<backend-port>` when running Vite.

## Daily routine
1. `git fetch origin`
2. `git rebase origin/main` in each active feature worktree.
3. `python scripts/sync_architecture_map.py --check` (docs-as-code consistency gate).
4. Run targeted stream tests.
5. Push feature branch with `--force-with-lease` only for owned feature branches.
6. Sync integration branch with no-ff merges for early conflict detection.

## Mandatory guardrail (task session lock)
Use the task session contract in every coding session:

1. Start the session from the worktree and branch you are actually using:
```bash
python scripts/task_session.py begin --request "<request>"
```
2. Check session identity before development commands when needed:
```bash
python scripts/task_session.py status
```
3. If the check fails:
- stop all code changes/tests in the wrong worktree,
- switch to the expected worktree/branch,
- start a fresh session from the correct location,
- do not recreate context manually through path/branch arguments.

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

## Minute Replay Parameter Baseline
- Runtime default profile (`configs/default.yaml`):
  - `strategy.execution_lag_minutes = 30`
  - `strategy.execution_max_wait_minutes = 360`
  - `strategy.entry_price_tolerance_pct = 0.02`
- Contract defaults (`src/moex_carry/contracts/strategy_test.py`) remain conservative:
  - `execution_lag_minutes = 20`
  - `execution_max_wait_minutes = 1440`
  - `entry_price_tolerance_pct = 0.0015`
- Validation gate (`src/moex_carry/config_resolver.py`):
  - `INTRADAY_MINUTE` requires `strategy.execution_lag_minutes >= 20`.

## Integration gate
- Required before merge to `main`:
  - API smoke for `/api/*` and `/api/v2/*`
  - `pytest -q tests/test_ui_api.py tests/test_signal_api.py`
  - Research subset: `pytest -q tests/hpo tests/backtest_v2`
