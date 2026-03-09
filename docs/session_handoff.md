# Session Handoff
Updated: 2026-03-09 11:18 UTC

## Goal
- Formalize `H4A` as the real execution baseline for manual use and document every operator-visible rule that is currently hidden inside the simulator.

## Task Request Contract
- Objective: document the current `H4A` runtime baseline as an explicit human-execution contract, close the gap between runtime config and operator-facing docs, and remove stale documentation that still frames `O1` as the active baseline.
- In Scope: operator-facing documentation for `H4A`, explicit manual rules for dynamic stop management and fallback behavior, baseline-status notes in research docs, and governance records that state `H4A` is the current execution baseline.
- Out of Scope: changing execution logic, retuning parameters, redesigning API payloads, or rerunning the whole hypothesis ladder.
- Constraints: keep the actual runtime profile unchanged, describe only what the live baseline already does, call out simulator-only assumptions where they cannot be executed manually, and keep governance/test gates green.
- Done Evidence: updated docs that state `H4A` rules unambiguously, aligned research/operator references, `python scripts/run_lean_gate.py`, and session/task validators.
- Priority Rule: first eliminate ambiguity for human execution, then align baseline-status documentation.

## Current Delta
- Published an operator-facing `H4A` runbook with explicit rules for LIMIT fallback, fill-dependent TP/SL recalculation, break-even, trailing stop, and time stop.
- Linked the new runbook from the signal-business process so manual use of the baseline is no longer implied or hidden.
- Marked the older O1-ladder page as historical and aligned current baseline wording around the already-active `H4A_CAP_OFF` runtime default.
- Added an evaluation-policy requirement that promoted dynamic execution baselines must ship with an explicit operator contract.
- Runtime logic remains unchanged; this loop aligned documentation and governance with the real baseline already used in config.

## Evidence
- `src/moex_carry/config.py`
- `scripts/run_morning_plan_walk_forward.py`
- `docs/signals-business-process.md`
- `docs/research/o1-execution-hypothesis-results-2026-03-06.md`
- `docs/research/execution-profiles-historical-review-no-minis-2026-03-06.md`
- `artifacts/research/wf_goal_v6_h4a_vs_baseline_risk_20260309.json`

## First-Time-Right Report
1. Confirmed coverage: runtime config, simulator rules, operator-flow docs, and research baseline notes are all available locally.
2. Missing or risky scenarios: simulator-only tie-break rules such as same-bar ordering cannot be converted into a human instruction without explicitly marking them as simulation assumptions.
3. Resource/time risks and chosen controls: keep logic unchanged, update only docs/governance records, and anchor every operator rule to the actual runtime parameters before declaring H4A the real baseline.
4. Highest-priority fixes or follow-ups: publish the H4A operator contract, align stale O1-baseline wording, and then decide whether API/UI reason taxonomy should be widened beyond generic `sl`.

## Repetition Control
- Max Same-Path Attempts: 2
- Stop Trigger: two consecutive documentation passes still leave unresolved ambiguity between runtime rules and operator instructions.
- Reset Action: reduce scope to a minimal operator runbook plus a short status note in the conflicting research docs.
- New Search Space: (1) operator runbook, (2) business-process delta, (3) baseline-status note in research history.
- Next Probe: write the exact H4A manual execution contract from runtime config and simulator behavior, then attach it to the existing signal-business process.

## Blockers
- None.

## Next Step
- Decide whether exit reasons and operator audit notes should be widened beyond generic `sl` and `time` so the UI/API can distinguish `protective_sl`, `initial_loss_sl`, and `same_bar_ambiguous`.

## Validation
- `python scripts/run_lean_gate.py`
- targeted doc/governance validators if touched
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_session_handoff.py`
