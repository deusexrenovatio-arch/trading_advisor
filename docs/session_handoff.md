# Session Handoff
Updated: 2026-02-23 13:27 UTC

## Goal
- Continue P3 decomposition with a line-budget ratchet while preserving idempotent action-path guarantees.

## Current Delta
- Completed idempotency+lease hardening: `idempotency_key` is required/unique, and scheduler/decision-action flows moved to dedicated UI modules.
- Extracted ops routes into `ui/routes_ops.py` and pretrade routes into `ui/routes_pretrade.py`; `app.py` now wires registrars as composition root.
- Extracted history/executions/backtests/rebalance/spread routes into `ui/routes_market_data.py` and wired from composition root.
- Extracted v2 research wrappers into `ui/routes_research.py` and wired registration from `ui/app.py`.
- Preserved test monkeypatch seams by resolving `MoexIssClient`, `run_delay_gate`, `build_spread_series`, and research runtime callables through `ui.app`.
- Reduced `src/moex_carry/ui/app.py` size from 5531 to 4459 lines across decomposition steps.
- Added dual line-budget policy (hard `max_lines_default=800`, soft `target_lines_default=700`) and advisory overrun reporting in taste validator.
- Synced governance records in `plans/PLANS.yaml` (`P1-API-DECOMPOSE-023/024/025`) and `memory/agent_memory.yaml` (`ADM-2026-02-23-020/021/022`, `AMP-2026-02-23-015/016/017`).

## Blockers
- None.

## Next Step
- Continue P3 decomposition by extracting the next route group from `ui/app.py` (actions/actionability block) into focused modules.
- Keep v1 adapter endpoints under sunset watch and remove auto-generated idempotency behavior only with explicit migration notice.

## Validation
- `python scripts/validate_architecture_policy.py`
- `pytest tests/test_storage_db.py tests/test_signal_api.py tests/test_api_v2.py -q`
- `pytest tests/test_signal_replay_incremental.py tests/test_signal_replay_core.py tests/test_signal_replay_minute_loader.py -q`
- `pytest tests/test_api_v2.py::test_v2_ops_health_and_slo_observability tests/test_api_v2.py::test_v2_pretrade_check_post tests/test_ui_api.py::test_pretrade_check_endpoint_returns_price_bands_and_volume_gate tests/test_ui_api.py::test_pretrade_check_endpoint_fail_opens_on_iss_transport_error -q`
- `pytest tests/test_signal_api.py::test_signals_history_endpoint_returns_rows tests/test_signal_api.py::test_signals_executions_endpoint_returns_rows tests/test_ui_api.py::test_spread_series_endpoint_uses_builder tests/test_api_v2.py::test_v2_portfolio_rebalance_preview_and_commit -q`
- `pytest tests/test_api_v2.py::test_v2_research_wrappers tests/test_api_v2.py::test_v2_hpo_status_fails_on_quality_gate -q`
- `python scripts/validate_taste_invariants.py`
- `python scripts/validate_session_handoff.py`
