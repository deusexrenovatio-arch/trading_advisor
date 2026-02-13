# Worktree Status

## Snapshot date
- 2026-02-13

## Streams
- `main` (`d:/New Project`): v2 foundation and docs.
- `refactor/app-core` (`d:/wt-refactor`): reserved for core-entity and adapter hardening.
- `chat/signals-backtest-lab` (`d:/wt-signals-backtest`): minute/HPO/performance artifacts.
- `feat/bot-integration` (`d:/wt-bot`): Telegram ACK and action integration.
- `chore/integration-sync` (`d:/wt-integration`): merge rehearsal and smoke checks.

## Merge order
1. `refactor/app-core`
2. `chat/signals-backtest-lab`
3. `feat/bot-integration`
4. docs/release updates

## Immediate integration checks
- API smoke for `/api/*` and `/api/v2/*`
- Targeted tests: UI API, signal API, HPO/backtest subsets
