# Risk Policy (Source of Truth)

## Core limits
- `max_positions`: from `risk_profile.max_positions`
- `max_daily_loss_pct`: from `risk_profile.max_daily_loss_pct`
- `max_open_risk_pct`: from `risk_profile.max_open_risk_pct`
- `max_leverage`: from `risk_profile.max_leverage`

## Gate policy
- `risk_gate`: hard block on limit breach.
- `pretrade`: block or hold when entry constraints fail.
- `news_gate`: severity-based reduction/block.
- `score_gate`: quality filter for actionable candidates.

## Action policy
- `ack`: records operator awareness; does not alter position balance.
- `enter|exit|hold_open`: execution-relevant actions.
- `idempotency_key`: mandatory dedup mechanism for repeated requests.
- `reason_code`: mandatory for policy-driven actions (for example `LEG_IMBALANCE_TIMEOUT`).

## Degraded modes
- ISS transport issues:
  - pretrade may switch to manual-confirm fail-open when configured.
  - event must be logged with advisory reason.
  - when `ui.ff_fail_closed_execution=true`, entry execution is blocked (`fail-closed`) until explicit pass/override.
  - override path is allowed only for privileged sources (`system|telegram`) and requires reason.
- One-leg execution imbalance:
  - auto-unwind policy can close stale imbalance via `POST /api/v2/policies/auto-unwind/run`.
  - timeout is controlled by `ui.auto_unwind_timeout_sec`.

## Review cadence
- Weekly policy review with product + risk owners.
- Any limit change requires a dated entry in `docs/planning/product-decisions.md`.
