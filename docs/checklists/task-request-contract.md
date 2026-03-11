# Task Request Contract Checklist

## Purpose
- Raise prompt quality to reduce rework and implicit scope drift.
- Force explicit operator tradeoffs before implementation starts.

## Mandatory Contract (before non-trivial implementation)
- Objective: one concrete outcome.
- In Scope: what can be changed now.
- Out of Scope: what is explicitly deferred.
- Constraints: time, risk, data, compute, policy, and environment limits.
- Done Evidence: exact commands, artifacts, or checks that prove completion.
- Priority Rule: how to choose when tradeoffs conflict (speed/quality/risk).

## Mandatory Repetition Control
- Max Same-Path Attempts: strict cap before forced strategy shift and must not exceed `configs/agent_incident_policy.yaml::incident.max_same_path_attempts`.
- Stop Trigger: explicit signal that the current approach is exhausted.
- Reset Action: concrete context reset action (new branch/worktree, fresh hypothesis list, cache/log reset).
- New Search Space: at least two alternative approaches.
- Next Probe: smallest test that distinguishes alternatives.

## Rejection Rules (blocker)
- Missing measurable objective.
- Scope and out-of-scope are mixed or contradictory.
- No completion evidence or only vague "it should work" criteria.
- Constraints omitted for high-risk or high-load work.
- Priority rule absent when requirements conflict.
- Repetition control omitted while the task has repeated failures or uncertain root cause.

## Enforcement
- Keep contract in `docs/session_handoff.md` under `## Task Request Contract`.
- Keep first-time-right report in `docs/session_handoff.md` under `## First-Time-Right Report`.
- Keep loop-breaker policy in `docs/session_handoff.md` under `## Repetition Control`.
- Keep task closeout fields in `docs/session_handoff.md` under `## Task Outcome`.
- Keep `## Blockers` accurate because `Outcome Status` is derived from `Decision Quality` plus unresolved blockers via `configs/task_outcome_policy.yaml`.
- Close the task with `python scripts/task_session.py end` to sync the final ledger record.
- Validation command:
  - `python scripts/validate_task_request_contract.py`
  - `python scripts/validate_task_outcomes.py`
