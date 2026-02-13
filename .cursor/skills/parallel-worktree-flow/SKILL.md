---
name: parallel-worktree-flow
description: "Baseline multi-stream development workflow for this repository using git worktree: clean bootstrap from main, branch-per-worktree isolation, daily rebase routine, integration branch checks, and merge ordering. Use when requests mention parallel development, several tasks at once, worktree, rebase strategy, branch synchronization, or conflict minimization."
---

# Parallel Worktree Flow

## Overview
Use this skill to run several implementation streams on one machine without branch collisions.

## Default topology
- Keep one task per branch and one branch per worktree.
- Keep `main` clean and protected.
- Keep a dedicated `wip/*` branch for unplanned local changes.
- Use an optional integration branch to detect conflicts before PR merge.

Recommended set for this repository:
- `wip/signals-backtest` in the current worktree (`d:/New Project`).
- `feat/bot-integration` in `../wt-bot`.
- `refactor/app-core` in `../wt-refactor`.
- `chore/integration-sync` in `../wt-integration`.

## Bootstrap workflow (default start)
1. Snapshot local dirty changes away from `main`:
```bash
git status --short --branch
git switch -c wip/<topic>
git add -A
git commit -m "wip(<scope>): snapshot before worktree split"
```

2. Refresh `main`:
```bash
git switch main
git fetch origin
git pull --ff-only
```

3. Create worktrees:
```bash
git worktree add ../wt-bot -b feat/bot-integration origin/main
git worktree add ../wt-refactor -b refactor/app-core origin/main
git worktree add ../wt-integration -b chore/integration-sync origin/main
```

4. Validate setup:
```bash
git worktree list
```

## Daily loop per stream
Run in each active feature/refactor worktree:
```bash
git fetch origin
git rebase origin/main
# run targeted tests for that stream
git push --force-with-lease
```

Rules:
- `--force-with-lease` is allowed only on your own feature branches.
- Rebase daily; do not let branches drift for multiple days.
- Keep PRs small and scoped to one concern.

## Integration branch loop
Use `chore/integration-sync` to detect collisions early:
```bash
git fetch origin
git rebase origin/main
git merge --no-ff refactor/app-core
git merge --no-ff feat/bot-integration
# run cross-stream smoke tests
git push origin chore/integration-sync
```

If conflicts appear, resolve them here first, then backport minimal fixes into source branches.

## Merge order policy
1. Foundation and contract-safe refactors.
2. Dependent feature streams (for example bot integration).
3. Runtime or strategy updates that depend on previous merges.
4. Documentation-only follow-ups.

## Conflict minimization rules
- Define file ownership per stream before coding.
- For shared interfaces, ship a small interface PR first.
- Avoid mixed concerns in one commit.
- If cross-stream risk is high, increase integration sync cadence.

## Completion checklist
- Every active stream is rebased on current `origin/main`.
- Integration branch merges all active streams cleanly.
- Stream tests and integration smoke checks pass.
- PRs are atomic and reviewable.
