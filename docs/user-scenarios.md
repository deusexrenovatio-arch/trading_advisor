# User Scenarios

Reference:
- End-to-end operator flow for `Signals` is documented in `docs/signals-business-process.md`.

## Component-by-component walkthrough (fresh review, 2026-03-02)

### C-01 Platform entry and routing
Actor: Operator
Goal: Reach target workspace without losing current task context.
Primary flow:
1. Open application root.
2. Navigate across `Trade Console`, `Research Lab`, `News Intelligence`, `Portfolio Control`.
3. Return to previous workspace.
Expected:
- Route is canonical (`/trade-console/*`, `/research-system/*`, `/news-intelligence`, `/portfolio-control`).
- Workspace switch does not break filter/action context unexpectedly.

### C-02 Decisions audit
Actor: Operator
Goal: Filter decisions and produce a traceable operator verdict.
Primary flow:
1. Apply strategy/instrument/risk/news/date filters.
2. Select decision row.
3. Submit operator action.
Expected:
- Decision details and evidence load from server projection/log.
- Operator and execution statuses are visible after submission.

### C-03 Signal action loop
Actor: Operator
Goal: Move from signal to execution with explicit gate status.
Primary flow:
1. Open `Signals`.
2. Inspect effective action and pre-trade status.
3. Execute action and verify execution history.
Expected:
- Signal status, pre-trade output, and execution audit are coherent.
- History reflects action without losing pair lifecycle context.

### C-04 Research cycle
Actor: Research engineer
Goal: Run backtest/HPO and track forward state in one workspace.
Primary flow:
1. Load parameter specs.
2. Run backtest and inspect report.
3. Run HPO and follow async status.
4. Inspect forward status.
Expected:
- All runs return structured status/result payloads.
- Result quality and promotion readiness are visible.

### C-05 News and portfolio operations
Actor: Operator
Goal: Combine event context with portfolio controls.
Primary flow:
1. Filter news by severity/ticker.
2. Load rebalance preview.
3. Validate risk checks before commit.
Expected:
- News rows preserve decision/entity references.
- Rebalance preview/commit stays auditable and risk-aware.

### C-06 Runtime reliability and integrations
Actor: Operator / Maintainer
Goal: Keep operational trust during degradation or retries.
Primary flow:
1. Check refresh status and ops health/SLO.
2. Use Telegram review bridge for signal confirmation.
3. Handle stale/ambiguous action flows.
Expected:
- Degraded states are explicit, not silent.
- Telegram review plus execution lifecycle remains idempotent and traceable.

## US-01 Configure the strategy
Actor: Operator
Goal: Define rates, costs, and risk limits for StockFuturesSpreadCarryAlpha.
Steps:
1. Open config (configs/default.yaml or environment overrides).
2. Set r_cb_annual and confirm r_fund_annual/r_disc_annual inherit by default.
3. Define cost, liquidity, and alpha thresholds.
Expected:
- Config loads without validation errors.
- Defaults are explicit and documented.

## US-02 Daily scan of pairs
Actor: User
Goal: See the current state of spread signals and top pairs.
Steps:
1. Run the signal cycle or wait for the scheduled refresh.
2. Open Top pairs and Signals views.
3. Click Reload to fetch the latest backend snapshot (last-good output).
4. Use `POST /api/signals/refresh` only when forced recompute is explicitly needed.
5. Open pair Details to confirm snapshot_as_of and signal timestamps.
6. In Signals details, open tab `РЎРёРіРЅР°Р»` and check grouped trading plan blocks.
Expected:
- Pairs are ranked by total_score.
- Each row includes spread_pct, rtc_pct, floor_rate_annual, score_floor, score_alpha.
- Signals list includes actionable entries with timestamp and execution plan fields:
  - entry spread corridor (`entry_spread_pct_min/max`),
  - spread TP/SL levels (`tp_spread_pct_level`, `sl_spread_pct_level`),
  - forecast exit horizon (`forecast_exit_days`).
- Signal details show grouped plan sections:
  - `РљРѕРЅС‚РµРєСЃС‚ СЃРёРіРЅР°Р»Р°`,
  - `РџР»Р°РЅ РІС…РѕРґР°`,
  - `Р РёСЃРє Рё СЃС‚РѕРї-СѓСЂРѕРІРЅРё`,
  - `РџСЂРѕРіРЅРѕР· РІС‹С…РѕРґР°`.
- If API does not provide plan fields (`entry_*`, `tp/sl`, `forecast_*`) for a row, the UI shows a coverage hint and keeps the screen readable without empty/broken tabs.
- If a pair is entered and not yet closed, `Signals` keeps this pair visible with explicit `hold_open` status.
- UI shows last successful recompute time.
- `GET /api/signals/refresh-status` exposes incremental telemetry:
  `pairs_recomputed`, `pairs_reused`, `pairs_skipped`, `skip_reason`.
- snapshot_as_of and signal timestamps reflect the latest run time using ISO 8601 with timezone (e.g., 2026-01-26T18:45:00Z).

## US-03 Drill into a pair
Actor: Operator
Goal: Inspect spread history and entry/exit flags.
Steps:
1. Open Top pairs and select a row.
2. View the spread series chart.
Expected:
- Series contains spread_mid and spread_pct.
- Entry/exit markers align with strategy rules.
- Tooltip timestamps match the snapshot_as_of time (ISO 8601 with timezone).

## US-04 Enter a position (floor + alpha)
Actor: Operator
Goal: Enter when floor_pass and liquidity_pass are true.
Steps:
1. Confirm decision flag ENTER_OK.
2. Execute trade with suggested quantities and exec prices.
Expected:
- TradeSignal records action=ENTER and reason codes.

## US-05 Early exit (alpha)
Actor: Operator
Goal: Exit within H days after favorable spread move.
Steps:
1. Monitor spread_pct vs TP_net.
2. Trigger exit when TP or SL conditions hit.
Expected:
- TradeSignal records action=EXIT with reason TP/SL.

## US-06 Hold to expiry or roll
Actor: Operator
Goal: Maintain floor carry when alpha exit does not trigger.
Steps:
1. Hold position until close_buffer_days.
2. Roll to next expiry if roll rules pass.
Expected:
- TradeSignal records action=EXIT with reason EXPIRY or ROLL.

## US-07 Backtest review
Actor: Operator
Goal: Validate share of alpha exits and holding profile.
Steps:
1. Run backtest v2 via UI (Backtest v2 tab) or CLI (`moex-carry backtest_v2`) or API (`POST /api/backtest/run`).
2. Review summary metrics, equity curve, and trades.
Expected:
- Metrics include share_alpha_exits and avg_hold_days.

## US-08 Risk/liquidity rejection
Actor: Operator
Goal: Understand why a pair is skipped.
Steps:
1. Open ranked list with decision flags.
2. Inspect skip reason and liquidity metrics.
Expected:
- Decision indicates SKIP_* with traceable thresholds.

## US-09 Forward cycle
Actor: Operator
Goal: Run the forward paper loop with EOD -> OPEN -> after close persistence.
Steps:
1. Initialize the forward run (`POST /api/forward/start`, `moex-carry forward_start`, or Forward UI tab).
2. Inspect status (`GET /api/forward/status` or `moex-carry forward_status`) or use the Forward status UI tab.
3. Run the forward paper engine at EOD to create next-open orders.
4. Run the OPEN phase to simulate fills and persist trades.
5. Run the after-close phase to mark to market and append equity.
Expected:
- State store persists portfolio and open orders across restarts.
- Trades are appended on OPEN fills.
- Equity curve appends one point per day.
- Alerts are emitted for missing data, wide spreads, or drawdown breaches.

## US-10 HPO run
Actor: Quant Researcher
Goal: Optimize strategy parameters using Backtest v2 as a black box.
Steps:
1. Define a search space for strategy parameters (e.g., z_window, TP_pct, SL_pct).
2. Configure walk-forward folds with embargo and choose evaluation mode (CONTINUOUS or WARMUP_THEN_FLAT).
2.1 (Optional) Set optimization metric (e.g., CAGR, IR, MaxDD) and mode (max/min).
3. Start an async HPO run (HPO UI tab submits `/api/hpo/run`).
3.1 (Optional) Provide a full JSON request in the HPO tab; it becomes the source of truth and overrides the form.
4. Poll `/api/hpo/status` (UI auto-refresh) until status changes to completed or failed.
5. Inspect the leaderboard when status is completed.
Expected:
- Folds respect train/val/test boundaries and embargo gaps.
- Objective penalizes violations and returns -INF on constraint breaches.
- HPO run returns run_id and progress counters.
- Status transitions: running -> completed (or failed with error).
- Leaderboard sorts by objective and best_config matches the top entry.

## US-11 Review decisions with server filters
Actor: Operator
Goal: Narrow the decisions list using server-side filters for faster reviews.
Steps:
1. Open Decisions tab.
2. Set Strategy/Instrument/Risk/News filters and a Created from/to date range.
3. Refresh.
Expected:
- API uses server-side filters (`strategy_type`, `primary_instrument`, `risk_state`, `news_severity`, `created_from`, `created_to`).
- Result list updates quickly without client-side heavy filtering.

## US-12 Confirm signal review from Telegram
Actor: Operator
Goal: Mark that a signal was reviewed from Telegram, then complete order and fill details in UI.
Steps:
1. Start `telegram_bot` with whitelist and send `/start`.
2. Wait for an actionable signal message in Telegram.
3. Click `Mark viewed` inline button.
4. Open Signals table in UI and reload.
Expected:
- Backend writes canonical `action=mark_viewed` and `status=viewed` to `signal_executions`.
- Active row shows `signal_viewed=true` and `signal_viewed_at/signal_viewed_by`.
- `signal_details_pending=true` remains until first `enter_filled` or `entry_cancelled` is logged.

## US-13 Morning bot liveness check
Actor: Operator
Goal: Receive one daily morning message confirming bot and data availability.
Steps:
1. Configure `daily_healthcheck_enabled=true` and `daily_healthcheck_time_local`.
2. Keep worker running past scheduled local time.
3. Review heartbeat message in Telegram.
Expected:
- Exactly one heartbeat message per registered chat per local calendar day.
- Message includes bot status, backend status, and active signals count.
- If backend is unavailable, heartbeat still arrives with `Backend: ERROR`.

## US-14 Keep pair actionable until explicit usage
Actor: Operator
Goal: Continue seeing actionable `enter` while intent is still valid, even if latest strategy row is `hold`.
Steps:
1. Generate an `enter` signal for a pair.
2. Let next cycle move pair to `hold` without explicit execution usage.
3. Open `/api/v2/pairs/actionability` or Signals tab.
Expected:
- Pair remains visible as `actionable_enter` while current bounds are executable within intent TTL.
- Row contains `intent_id`, current entry bounds, and origin links to source signal history.
- `mark_viewed` alone does not suppress Telegram delivery for that intent.
- Delivery is suppressed only after explicit execution progression such as `enter_submitted`, `enter_filled`, `entry_cancelled`, or `manual_override`.

## US-15 Telegram out-of-range update without spam
Actor: Operator
Goal: Get one update if sent entry leaves the original corridor, without repeated spam.
Steps:
1. Receive `enter` in Telegram and keep it unused.
2. Let market move outside original entry bounds.
3. Let worker run multiple polling cycles.
Expected:
- Worker sends one out-of-range update containing current vs planned bounds.
- Repeated cycles with same fingerprint do not create additional out-of-range messages.
- If recalculation yields a new executable plan revision, worker can send one new enter update for that new fingerprint.
- New fingerprint for same pair still respects pair-level cooldown.

## US-16 Pair-level action API for UI and Telegram
Actor: Operator
Goal: Confirm review and executions on pair + intent level without depending on transient signal rows.
Steps:
1. Fetch pair row from `/api/v2/pairs/actionability`.
2. Submit `POST /api/v2/pairs/{pair_id}/actions` with `action=mark_viewed|enter_submitted|enter_filled|entry_cancelled|exit_filled|confirm_followup|manual_override` and `intent_id` when required.
3. Reload actionability feed.
Expected:
- Response includes `status`, `pair_id`, `action`, `intent_id`, and `fail_closed`.
- Pair projection reflects updated intent/position state.
- Legacy signal execution audit remains traceable via resolved `signal_id` when available.

## US-17 Single-instrument actionable signal
Actor: Operator
Goal: See and use actionable signals for a single stock or future using the same workflow as pair signals.
Steps:
1. Open `/api/v2/signals/actionability` with `entity_type=instrument`.
2. Filter by `instrument_type=stock` or `instrument_type=future`.
3. Submit action via `POST /api/v2/entities/{entity_type}/{entity_id}/signals/actions`.
Expected:
- Instrument rows expose the same lifecycle fields (`actionability_state`, `intent`, `delivery`).
- Action API behavior (idempotency/fail-closed/audit) matches pair workflow.

## US-18 Conflicting multi-source evidence handling
Actor: Operator
Goal: Understand why entry is blocked when sources disagree.
Steps:
1. Open one actionable entity row in Signals details.
2. Inspect `evidence_items`, `evidence_summary`, and `policy_outcome`.
3. Verify at least one scenario with technical/fundamental support and contradictory news.
Expected:
- Evidence block shows support/oppose weights and conflict score.
- If veto source is active (for example high-severity adverse news), policy status becomes `block`.
- Delivery is suppressed with explicit reason, not silently removed from visibility.

## US-19 Review and reduced-risk policy states
Actor: Operator
Goal: Distinguish between hard block, manual-review state, and reduced-risk actionable state.
Steps:
1. Open `/api/v2/signals/actionability` and inspect entities with `policy_outcome.status`.
2. Open details and inspect `policy_outcome.gate_trace`.
Expected:
- `policy_outcome.status=review` maps to visible `review_entry` state and requires manual confirmation.
- `policy_outcome.status=reduce` stays actionable but includes explicit risk-size reduction metadata.
- Policy precedence is auditable through gate priorities and reason codes.

## US-20 Open position with fresh entry intent
Actor: Operator
Goal: Keep seeing fresh valid entry opportunities even when position is already open.
Steps:
1. Ensure entity has open position from execution ledger.
2. Generate a new in-range active entry intent for the same entity.
3. Open Signals and reload.
Expected:
- Open position is shown as `hold_open` overlay from position facts.
- Fresh entry intent remains visible/actionable if policy and range permit.
- Entry suppression happens only after explicit usage for that intent.

## US-21 Idempotent UI action submission
Actor: Operator
Goal: Safely retry action submissions without duplicate execution side effects.
Status: Implemented in UI/backend on 2026-03-02.
Steps:
1. Submit `mark_viewed|enter_submitted|enter_filled|entry_cancelled|exit_filled|confirm_followup|manual_override` from Signals UI and `approve|reject|execute` from Decisions UI.
2. Repeat the same request after simulated network timeout/retry.
Expected:
- UI request payload includes explicit `idempotency_key`.
- Duplicate retry returns deterministic `duplicate` response and does not create a new execution fact.
- New `idempotency_key` creates a new auditable action event.

## US-22 Instrument action ambiguity recovery
Actor: Operator
Goal: Resolve instrument-level action when one instrument belongs to multiple active pairs.
Steps:
1. Call `POST /api/v2/entities/instrument/{entity_id}/signals/actions` without pair context.
2. Receive ambiguity response.
3. Repeat action with explicit `pair_id`.
Expected:
- API returns explicit ambiguity payload with `candidate_pairs`.
- Follow-up action with `pair_id` resolves deterministically and remains auditable.

## US-23 Refresh degradation operational handling
Actor: Operator
Goal: Continue safe operations when refresh engine is `busy`, `degraded`, or `error`.
Steps:
1. Inspect `GET /api/signals/refresh-status`.
2. Observe non-`ok` status and follow recovery path.
Expected:
- Status includes actionable fields (`last_error`, `skip_reason`, watermark/lag telemetry).
- Operator can distinguish transient busy state from stale/degraded state.
- Recovery path avoids silent stale execution assumptions.

## US-24 Portfolio commit risk gate
Actor: Operator
Goal: Avoid committing rebalance plans that violate risk checks without explicit override.
Status: Server-side hard gate implemented on 2026-03-02.
Steps:
1. Request `GET /api/v2/portfolio/rebalance/preview`.
2. Detect one or more failed risk checks.
3. Attempt commit.
Expected:
- System blocks commit by default when hard risk checks fail, or requires explicit override metadata.
- Final commit payload remains auditable with actor, reason, and timestamp.

## US-25 API v2 payload and traceability guardrail
Actor: Integrator / Maintainer
Goal: Keep API interactions debuggable and bounded under heavy clients.
Steps:
1. Send an oversized POST request to `/api/v2/*`.
2. Send valid request and inspect response headers.
Expected:
- Oversized payload gets `413 payload_too_large`.
- Responses include `X-Request-Id` for deterministic traceability.
- Structured logs preserve path/method/status/request_id/duration for incident review.


