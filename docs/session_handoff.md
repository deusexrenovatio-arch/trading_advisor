# Session Handoff
Updated: 2026-03-06 08:44 UTC

## Goal
- Run futures signals in `signals-only` paper mode on live MOEX contour with existing Telegram format, and keep execution baseline on `O1`.

## Task Request Contract
- Objective: keep current Telegram signal UX, wire launch path for live paper-forward from today, align default execution policy to `O1`, and split live signal flow by strategy stream.
- In Scope: `src/moex_carry/config.py`, launch scripts in `scripts/`, strategy/actionability/telegram runtime paths, and operator docs (`README.md`).
- Out of Scope: probability-gate restoration, Telegram message schema redesign, broker auto-trading.
- Constraints: deterministic behavior, no breaking API/worker contracts, governance gates green.
- Done Evidence: O1 default config committed, live launch script added, strategy stream split wired through API/TG worker, docs updated.

## Current Delta
- Default morning execution policy switched from O4 TP hard-cap to O1 behavior (`SignalEngineMorningExecutionConfig.max_profit_ticks: 120 -> 0`).
- Added orchestration script `scripts/start_forward_paper_live.ps1` for backend/refresh/worker/forward-start bootstrap.
- Launch script now auto-loads `scripts/moex-carry.local.ps1` (unless `-NoLocalEnv`) and auto-fetches raw data on `Missing raw data` before retrying forward start.
- Added strategy metadata propagation (`strategy_id`, `strategy_type`, `strategy_stream`) into actionability payloads and signal fingerprints.
- Telegram worker now shows strategy label in message and separates cooldown/daily keys by `{stock}|{future}|{strategy_stream}`.
- Added regression checks for strategy filters/cooldown split (`tests/test_api_v2.py`, `tests/test_telegram_worker.py`, `tests/test_signal_cycle.py`).

## Accepted Profile
- Profile id: `O1`
- Parameters:
  - `break_even_rr=0.1`
  - `break_even_buffer_ticks=2`
  - `tp_rr=0.6`
  - `sl_rr=2.5`
  - `max_holding_minutes=180`
  - `max_profit_rr=0.3`
  - `max_profit_ticks=0` (disabled hard cap)
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
- Comparison artifact (seed124):
  - `artifacts/research/wf_goal_v6_h24_causal_rerun_execution_fixed_O1_limitfallback10m1t_frontnearest_seed124_20260305.json`
  - `artifacts/research/wf_goal_v6_h24_causal_rerun_execution_fixed_O4_frontnearest_seed124_20260306.json`
- Key diff:
  - same trade count (`filled=222`) but `O1 net_ticks_sum=12605.5` vs `O4 net_ticks_sum=7362.0`
  - driver: O4 `max_profit_ticks=120` clips profitable tails.
- Live launch evidence (today, 2026-03-06):
  - `powershell -ExecutionPolicy Bypass -File scripts/start_forward_paper_live.ps1 -ForceFullRefresh`
  - refresh: `status=ok`, `engine=unified_minute_replay`
  - forward: `run_id=fwd-05f7053414`, `status=ready`
- Strategy split validation:
  - `pytest tests/test_api_v2.py tests/test_telegram_worker.py tests/test_signal_cycle.py -q` -> `53 passed`
  - runtime process check confirms both `moex_carry.cli ui` and `moex_carry.cli telegram_bot` are running.

## First-Time-Right Report
1. Confirmed coverage: baseline switch + launch orchestration + strategy stream split (API + Telegram) + docs.
2. Missing or risky scenarios: Telegram worker still requires env/token (`MOEX_CARRY_TELEGRAM__BOT_TOKEN`, `...ALLOWED_USER_IDS`); script now auto-loads local env file but still warns/skips worker if creds are absent.
3. Resource/time risks and controls: live refresh can be heavy; `-ForceFullRefresh` is explicit opt-in.
4. Highest-priority follow-up: add scheduled phase runner for forward `EOD -> OPEN -> AFTER_CLOSE` if operator wants full daily automation.

## Blockers
- None for code path.
- Runtime prerequisite for Telegram delivery: bot token + whitelist must be set in env or `scripts/moex-carry.local.ps1`.

## Next Step
- Start live contour:
  - `powershell -ExecutionPolicy Bypass -File scripts/start_forward_paper_live.ps1 -ForceFullRefresh`

## Validation
- `python scripts/run_lean_gate.py`
- `powershell -ExecutionPolicy Bypass -File scripts/start_forward_paper_live.ps1 -CheckOnly`
- `powershell -ExecutionPolicy Bypass -File scripts/start_forward_paper_live.ps1 -ForceFullRefresh`
- `pytest tests/test_api_v2.py tests/test_telegram_worker.py tests/test_signal_cycle.py -q`
