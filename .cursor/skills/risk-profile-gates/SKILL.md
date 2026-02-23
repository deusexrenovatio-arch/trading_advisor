---
name: risk-profile-gates
description: Deterministic risk profile gates for intraday futures decisions. Use for risk-limit validation, strategy rechecks, and mandatory pre-push gates on trading decision logic. Co-use with intraday-futures-trading-advisor and moex-instruments-costs.
---

# Risk Profile Gates

## Purpose
Define fixed risk limits that must be satisfied before any decision is approved. Output must be deterministic pass/fail with explicit reasons.

## Skill dependencies and lifecycle gates
- Planning phase: use with `intraday-futures-trading-advisor`.
- Cost consistency phase: pair with `moex-instruments-costs`.
- Event-risk phase: add `news-geopolitics-filter` when external volatility risk is material.
- Recheck/pre-push phase: rerun this gate whenever risk limits or execution constraints change.


## Repository governance baseline (mandatory)
- Follow `docs/workflows/skill-governance-sync.md` for mandatory repository gates (worktree guard, lean loop, plans/memory/handoff, pre-push blockers, repeated-issue escalation).
- Keep this skill focused on domain workflow; do not duplicate repository governance details here.

## Required inputs
- `account_equity`
- `account_currency`
- `max_risk_per_trade_pct`
- `max_daily_loss_pct`
- `max_open_risk_pct`
- `max_leverage`
- `max_margin_pct`
- `max_contracts_per_instrument`
- `max_positions`
- `max_correlated_exposure_pct`
- `stop_loss_required`
- `time_stop_minutes`
- `slippage_tolerance_ticks`

## Deterministic checks
- All percentage limits are within `0.1` to `10.0` inclusive.
- `max_open_risk_pct >= max_risk_per_trade_pct`.
- `max_daily_loss_pct >= 2 * max_risk_per_trade_pct`.
- `max_leverage` is within `[1, 10]`.
- `max_margin_pct` is within `[10, 100]`.
- `max_contracts_per_instrument` is a positive integer.
- `max_positions` is a positive integer.
- `stop_loss_required` is `true`.
- `time_stop_minutes` is within `[1, 240]`.
- `slippage_tolerance_ticks` is within `[0, 10]`.

## Output JSON template
```json
{
  "risk_profile": {
    "account_equity": 100000,
    "account_currency": "RUB",
    "max_risk_per_trade_pct": 0.5,
    "max_daily_loss_pct": 2.0,
    "max_open_risk_pct": 1.5,
    "max_leverage": 5,
    "max_margin_pct": 60,
    "max_contracts_per_instrument": 20,
    "max_positions": 6,
    "max_correlated_exposure_pct": 40,
    "stop_loss_required": true,
    "time_stop_minutes": 90,
    "slippage_tolerance_ticks": 2
  },
  "risk_gate_result": {
    "passed": true,
    "checks": [
      {
        "id": "risk_limits_range",
        "passed": true,
        "message": "All limits within allowed ranges."
      }
    ],
    "actions": []
  }
}
```
## Mandatory pre-push guidance
- Run `python scripts/sync_architecture_map.py --check` when boundaries or integrations are touched.
- Run required checks from `docs/DEV_WORKFLOW.md` for touched areas; treat failures as blockers.
- If contracts/registry/docs changed, update source-of-truth artifacts before push and keep notes in AGENTS or PR summary.
