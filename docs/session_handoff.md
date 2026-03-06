# Session Handoff
Updated: 2026-03-06 10:03 UTC

## Goal
- Keep `O1` as the default futures execution baseline and require explicit sign-off for any future drift relative to `O1`.

## Task Request Contract
- Objective: fix `O1` as the default execution baseline and codify mandatory drift analysis for future rebases or profile changes that move away from `O1`.
- In Scope: `src/moex_carry/config.py`, config-default regression coverage, and governance memory/handoff/plan records for rebase-drift decisions.
- Out of Scope: removing advanced execution features, changing non-execution strategy logic, or changing Telegram/API live-signal contracts.
- Constraints: deterministic behavior, `O1` stays default until a replacement beats it and is explicitly accepted, governance gates green.
- Done Evidence: `O1` defaults restored, regression test added for `O1`, rebase-drift rule recorded in plans/memory/handoff.
- Priority Rule: branch goal follows `O1` first; merged changes that drift from `O1` require written analysis and explicit accept/revert decision.

## Current Delta
- Default morning execution policy again matches `O1`.
- `O1` is now the comparison anchor for runtime and research metrics.
- Alternative execution behavior remains available through explicit config or CLI overrides.
- Added regression coverage for `O1` defaults in `tests/test_config_loading.py`.
- Recorded a durable rebase-drift rule in `memory/agent_memory.yaml` and `plans/PLANS.yaml`.
- Any baseline-changing rebase now requires a write-up, `O1` comparison, and a branch-goal decision.

## Accepted Profile
- Profile id: `O1`
- Parameters:
  - `break_even_rr=0.1`
  - `break_even_buffer_ticks=2`
  - `tp_rr=0.6`
  - `sl_rr=2.5`
  - `max_holding_minutes=180`
  - `max_profit_rr=0.3`
  - `max_profit_ticks=0`
  - `trail_activation_rr=0.1`
  - `trail_offset_ticks=2`
  - `same_bar_policy=open_direction`
  - `limit_entry_improve_ticks=1`
  - `limit_fallback_to_market_minutes=10`
  - `limit_fallback_slip_ticks=1`
  - `tp_cost_mult=0.2`
  - `sl_cost_mult=0.7`
  - `exit_cost_mult=0.4`

## Evidence
- O1 reference artifacts:
  - `artifacts/research/wf_goal_v6_h24_causal_rerun_execution_fixed_O1_limitfallback10m1t_frontnearest_seed124_20260305.json`
  - `artifacts/research/wf_goal_v6_h24_execution_profile_compare_O4_vs_M3_seed124_20260306.json`
- Drift analysis example:
  - same generated setup `BRH6:ORB_BREAKOUT:BUY:7171` stayed stable after rebase, so the drift source was execution semantics, not signal generation.
  - future drift decisions are accepted or rejected against `O1`, not against incidental merged defaults.
- Guardrail evidence:
  - `tests/test_config_loading.py` now asserts `O1` default execution values directly.
  - `memory/agent_memory.yaml` and `plans/PLANS.yaml` now require explicit baseline-drift write-up and branch-goal decision.

## First-Time-Right Report
1. Confirmed coverage: restored `O1` defaults, added regression test for them, and recorded mandatory `O1`-relative drift analysis rule in governance memory.
2. Missing or risky scenarios: non-`O1` overrides can still reintroduce drift if they are used without explicit artifact comparison.
3. Resource/time risks and chosen controls: minimal patch changes only default baseline definition and governance records, reducing collateral regression risk.
4. Highest-priority fixes or follow-ups: keep naming every new execution profile explicitly and compare it against `O1` before promotion.

## Repetition Control
- Max Same-Path Attempts: 2
- Stop Trigger: two consecutive unsuccessful attempts on the same push/rebase failure path.
- Reset Action: stop retry loop, inspect failing gate details, and patch only the minimal contract violation before retry.
- New Search Space: (1) handoff contract sections, (2) governance validator expectations, (3) rebase conflict resolution strategy.
- Next Probe: rerun `python scripts/validate_task_request_contract.py` before the next push.

## Blockers
- None for code path.

## Next Step
- If execution-profile experiments continue, run them only via explicit overrides and compare against `O1` before promoting any new default.

## Validation
- `python scripts/run_lean_gate.py`
- `pytest tests/test_config_loading.py tests/test_morning_plan_walk_forward.py -q`
