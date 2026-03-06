# CTX-NEWS

## Scope
News intelligence, shock pipelines, and event-driven alerting flows.

## Owned Paths
- `src/moex_carry/news_live_bridge.py`
- `src/moex_carry/news_live_clients.py`
- `src/moex_carry/news_live_runtime.py`
- `src/moex_carry/news_live_scoring.py`
- `src/moex_carry/news_mode_compare.py`
- `src/moex_carry/news_shock_automation.py`
- `src/moex_carry/news_shock_pipeline.py`
- `src/moex_carry/news_shock_readiness.py`
- `src/moex_carry/shock_alert_delivery.py`
- `src/moex_carry/shock_episodes.py`

## Guarded Paths (do not change in this context)
- `src/moex_carry/storage/`
- `contracts/`
- `ui-web/`

## Input/Output Contracts
- Input: provider fetches, scored stories, shock episodes, and event metadata.
- Output: news-gate inputs, shock labels, alerts, and event-aware runtime projections.

## Minimum Checks
- `python scripts/run_lean_gate.py`
- `pytest tests/test_news_live_runtime.py -q`
