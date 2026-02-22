# 2026-02-22 Agent trajectory and traceability hardening

- Added blocking `trajectory` and `context-budget` dimensions to `configs/quality_scorecards.yaml`.
- Added API v2 request-id propagation (`X-Request-Id`) and structured log correlation.
- Added API v2 payload-size guard via `ui.max_api_payload_bytes` with `413 payload_too_large`.
- Added regression coverage in `tests/test_api_v2.py` for request-id headers and oversized payload rejection.
