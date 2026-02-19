# First-Time-Right Gate Checklist

## Purpose
- Reduce repeated cycles by forcing complete user-scenario and execution planning before implementation.
- Apply equally to research and user-facing business logic.

## When to use
- Any non-trivial feature, fix, or analysis.
- Any task with potentially long runtime, heavy compute, or heavy network traffic.
- Any repeated issue or regression-prone area.

## 1) Goal Contract (required before coding)
- User outcome: what exact user decision/action this changes.
- Acceptance criteria: concrete pass/fail outputs.
- Out-of-scope: what is explicitly not solved now.
- Assumptions: what must be verified, not guessed.

## 2) User-Case Completeness Gate
- Primary success flow defined.
- Edge flows defined (empty/noisy/stale/partial data).
- Negative flows defined (invalid inputs, unavailable deps, auth/permissions if applicable).
- Retry/interruption flow defined (timeouts, user cancellation, restart).
- Error UX/API contract defined (status, message, fallback behavior).

## 3) Budget and Stop/Replan Gate
- Runtime estimate documented.
- Network/IO estimate documented.
- Compute plan selected: smoke-first then scale.
- Stop/replan trigger set (for example runtime > expected by 2x, queue growth, low signal quality).
- Progress checkpoints defined (what to report and how often).

## 4) High-Load Readiness Gate
- Work partitioning (chunking/sharding) defined.
- Parallelism strategy and limits defined.
- Cache/reuse/resume path defined.
- Backpressure or concurrency cap defined.
- Fallback mode defined if high-load path degrades.

## 5) Context Integrity Gate
- Every change maps to the main task objective.
- No detached side-work without direct user value.
- Contract/docs/tests/code alignment checked.

## 6) Predictive Next-Needs Gate
- Likely next 1-2 user needs identified.
- Extension points intentionally preserved (params, schema, module boundaries).
- Minimal future-proof tests added where cheap.

## 7) Repeated-Issue Escalation Gate
- If same issue reappears, run structured root-cause review before new patch.
- Capture findings, hypotheses, and regression checklist.
- Do not continue patching until primary failure mode is explicit.

## Required output format
1. Confirmed coverage.
2. Missing or risky scenarios.
3. Resource/time risks and chosen controls.
4. Highest-priority fixes or follow-ups.
