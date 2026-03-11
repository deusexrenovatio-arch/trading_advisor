# Signal Agent Continuity Runbook

Use this runbook when the same signal/data/runtime issues repeat across sessions, worktrees, or branches.

## Goal
- Keep signal outputs trustworthy for user decisions.
- Prevent repeated loops: stale data, wrong worktree, wrong runtime, and metric misinterpretation.

## Canonical Contracts
### Runtime and worktree
- Every edit and run must start with:
  - `python scripts/task_session.py begin --request "<request>"`
- UI/worker process command line must point to the intended worktree config.
- Do not validate outputs from one worktree and claim results for another.

### Data and storage layers
- Minute source data (per pair):
  - `data/output/intraday_minute_series/*.csv`
- Unified projection outputs (canonical runtime projection):
  - `data/output/unified/top_pairs.csv`
  - `data/output/unified/signals.csv`
  - `data/output/unified/backtest_summary.csv`
- Root aliases (manual inspection compatibility):
  - `data/output/top_pairs.csv`
  - `data/output/signals.csv`
  - `data/output/backtest_summary.csv`
- Execution/state DB:
  - `data/moex_carry.db`
  - `signal_history` = periodic projection snapshots.
  - `signal_executions` = real user/bot actions.

### Signal semantics
- `trades_closed`, `entry_signals`, `exit_signals` in projection are replay sample metrics.
- They are not equal to real executed orders.
- Real actions must be read from `signal_executions` and API execution endpoints.

## Repeated Failure Classes and Fixes
### 1) Wrong worktree drift
- Symptom:
  - “Fix exists but not visible in current branch/worktree.”
- Root cause:
  - edits/tests were run in another checkout.
- Fix:
  - enforce `task_session` begin/status before edits and long runs.
  - print active worktree in progress updates.

### 2) Stale projection confusion
- Symptom:
  - `data/output/signals.csv` contradicts runtime/API.
- Root cause:
  - reading legacy root files while unified outputs changed.
- Fix:
  - treat `data/output/unified/*` as canonical.
  - publish/sync root aliases from unified refresh.

### 3) “No actionable enter” mismatch
- Symptom:
  - expected enters disappear after logic changes.
- Root cause:
  - score gate/default filter, pending-intent usage, or out-of-date snapshot.
- Fix:
  - check `/api/v2/signals/active?require_score_gate=false` and `true`.
  - verify pending intent, explicit usage, and position-open exceptions.

### 4) Overtrading distorts PnL/score
- Symptom:
  - unrealistically high score/PnL with hundreds of replay closes.
- Root cause:
  - high turnover + annualized alpha outliers dominate score.
- Fix:
  - enforce turnover gate (`trades_per_day`).
  - cap alpha contribution before score composition.

### 5) Memory pressure during refresh/UI runs
- Symptom:
  - long refresh, RAM growth, unstable local runtime.
- Root cause:
  - cache key churn and repeated full replay.
- Fix:
  - stable replay cache key strategy.
  - bounded cache size in config.
  - prefer incremental refresh unless explicitly force-full.

## Verification Checklist
Run this after any signal lifecycle/data/scoring fix:

1. `python scripts/run_loop_gate.py --from-git --git-ref HEAD`
2. Confirm process source:
  - active UI command line points to intended worktree/config.
3. Refresh signal projection once:
  - `/api/signals/refresh` (and force-full only when needed).
4. Compare projection sources:
  - `data/output/unified/signals.csv` is updated.
  - root alias CSV is synchronized with unified.
5. Validate API behaviors:
  - `/api/v2/signals/active?require_score_gate=false`
  - `/api/v2/signals/active?require_score_gate=true`
  - `/api/v2/signals/history`
6. Validate execution semantics:
  - `signal_history` volume can be large (snapshots).
  - `signal_executions` reflects real user/bot actions.
7. Validate Telegram anti-spam expectations via tests and runtime fields:
  - usage flags, TTL, out-of-range update behavior.

## Non-Negotiable Reporting in Agent Updates
- State exact worktree/branch being used.
- State exact data source path used for the claim.
- Distinguish:
  - projection metric (`trades_closed` sample),
  - real execution metric (`signal_executions`).
- If values differ between files, explicitly name both file paths and timestamps.


