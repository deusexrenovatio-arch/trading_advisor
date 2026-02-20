# Operational KPI

## Trade Console
- `time_to_first_action_sec`
- `blocked_action_rate`
- `signal_to_execution_latency_sec`
- `tab_switch_count`

Definitions
- `time_to_first_action_sec`: seconds from workspace session start to first operator action (`decision approve/reject` or `signal execute`).
- `blocked_action_rate`: share of entry-intent signals currently blocked by pre-trade (`hold_pretrade`/`check_pretrade`) in Trade Console Signals view.
- `tab_switch_count`: count of workspace/tab route switches during current UI session.

## Research Lab
- `baseline_reproducibility_rate`
- `oos_improvement_rate`
- `stress_survival_rate`

## News Intelligence
- `news_to_signal_link_coverage`
- `high_severity_block_ratio`

## Portfolio Control
- `rebalance_plan_acceptance_rate`
- `turnover_limit_breach_rate`

## Quality
- `api_v2_contract_pass_rate`
- `idempotent_action_duplicate_rate`
- `projection_mismatch_rate`
- `app_startup_time_sec`
- `core_api_journey_p95_sec`

## Backend Ops (v2)
- `v2_pretrade_check_p95_ms`
- `v2_signals_actions_p95_ms`
- `execution_rejections_fail_closed_15m`
- `pretrade_failures_15m`
- `pretrade_degraded_15m`
- `auto_unwind_triggered_15m`
- `auto_unwind_errors_15m`

Operational endpoints
- `GET /api/v2/ops/health`: readiness/liveness snapshot with DB and scheduler status.
- `GET /api/v2/ops/slo`: runtime SLO snapshot with alert flags.

Default alert thresholds
- `v2_pretrade_check_p95_ms > 1500`
- `v2_signals_actions_p95_ms > 800`
- `execution_rejections_fail_closed_15m >= 5`
- `pretrade_failures_15m >= 10`
- `auto_unwind_errors_15m >= 1`

CI budget checks
- `tests/perf/test_app_startup_runtime.py`: startup <= 12s.
- `tests/perf/test_api_journey_runtime.py`: critical GET journey calls <= 2s each.
