---
name: parallel-worktree-flow
description: "Baseline multi-stream development workflow for this repository using git worktree: clean bootstrap from main, branch-per-worktree isolation, daily rebase routine, integration branch checks, merge ordering, and pre-push gates. Use at the start of new development, during stream synchronization, and before merge/push."
---

# Parallel Worktree Flow

## Overview
Use this skill to run parallel implementation streams on one machine without branch collisions and with deterministic pre-push gates.

## Skill dependencies and lifecycle gates
- Start phase: run this skill before any new feature/refactor stream.
- Domain phase: after bootstrap, invoke domain skill(s) for the stream (`trading-ui-dashboard`, `ml-backtest-hpo-lab`, or strategy gates).
- Recheck phase: ensure daily rebase + integration sync before rerunning domain verification.
- Pre-push phase: run mandatory checks from `docs/DEV_WORKFLOW.md` and stream-specific validations.


## Repository governance baseline (mandatory)
- Follow `docs/workflows/skill-governance-sync.md` for mandatory repository gates (worktree guard, lean loop, plans/memory/handoff, pre-push blockers, repeated-issue escalation).
- Keep this skill focused on domain workflow; do not duplicate repository governance details here.

## Default topology
- Keep one task per branch and one branch per worktree.
- Keep `main` clean and protected.
- Keep an integration branch for early conflict detection.

Repository baseline topology:
- `d:/New Project` -> `main` (baseline, release prep).
- `d:/wt-refactor` -> `refactor/app-core` (contracts/core entities).
- `d:/wt-signals-backtest` -> `chat/signals-backtest-lab` (research/performance).
- `d:/wt-bot` -> `feat/bot-integration` (ACK/actions integration).
- `d:/wt-integration` -> `chore/integration-sync` (integration-only sync and smoke).

## Dev ports policy
- `main` worktree:
  - backend: `8050`
  - frontend: `5176`
- Feature worktrees use dedicated ports:
  - `d:/wt-refactor`: backend `8061`, frontend `5186`
  - `d:/wt-signals-backtest`: backend `8062`, frontend `5187`
  - `d:/wt-bot`: backend `8063`, frontend `5188`
  - `d:/wt-integration`: backend `8064`, frontend `5189`
- For frontend worktrees set:
  - `VITE_API_PROXY_TARGET=http://127.0.0.1:<backend-port>`

## Bootstrap workflow (default start)
1. Refresh `main`:
```bash
git switch main
git fetch origin
git pull --ff-only
```

2. Validate task request contract before coding:
```bash
python scripts/validate_task_request_contract.py
```

3. Create worktrees from `origin/main` (if missing):
```bash
git worktree add ../wt-refactor -b refactor/app-core origin/main
git worktree add ../wt-signals-backtest -b chat/signals-backtest-lab origin/main
git worktree add ../wt-bot -b feat/bot-integration origin/main
git worktree add ../wt-integration -b chore/integration-sync origin/main
```

4. Validate setup:
```bash
git worktree list
```

## Daily loop per stream
Run inside each active feature/refactor worktree:
```bash
git fetch origin
git rebase origin/main
python scripts/sync_architecture_map.py --check
# run targeted stream tests
git push --force-with-lease
```

Rules:
- Use `--force-with-lease` only on owned feature branches.
- Rebase daily; do not let branches drift.
- Keep PRs small and single-concern.

## Integration branch loop
Use `chore/integration-sync` to detect collisions early:
```bash
git fetch origin
git rebase origin/main
git merge --no-ff refactor/app-core
git merge --no-ff chat/signals-backtest-lab
git merge --no-ff feat/bot-integration
# run integration smoke checks
git push origin chore/integration-sync
```

If conflicts appear, resolve in integration branch, then backport minimal fixes to source branches.

## Merge order policy
1. `refactor/app-core`
2. `chat/signals-backtest-lab`
3. `feat/bot-integration`
4. docs/release-only follow-ups

## Mandatory pre-push guidance
Run before push/PR finalization:
```bash
python -m pip install -e ".[dev]"
python scripts/sync_architecture_map.py --check
pytest
npm --prefix ui-web ci
npm --prefix ui-web run lint
npm --prefix ui-web run build
```

## Completion checklist
- Every active stream rebased on current `origin/main`.
- Integration branch merges active streams cleanly.
- Required pre-push gate commands pass.
- Stream-specific checks and smoke checks pass.
- PRs are atomic and reviewable.

