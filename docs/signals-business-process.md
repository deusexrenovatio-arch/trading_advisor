# Signals Tab Business Process (Stock/Futures Spread, ISS Delayed Mode)

## Purpose
Define an end-to-end operator process in `Signals` from entry decision to exit execution for two-leg stock/futures trades under ISS delayed data constraints.

## Scope
- Included:
  - Signal review and filtering in `Signals`
  - Entity types: `pair` and single `instrument` (stock/future)
  - Multi-source evidence composition (`technical`, `fundamental`, `news`, `risk`, `liquidity`)
  - Pre-trade validation (`/api/pretrade/check`)
  - Manual execution logging (`/api/signals/execute`)
  - Position monitoring and exit handling
  - Audit trail in signal history and execution history
- Excluded:
  - Broker auto-routing and guaranteed fills
  - Real-time low-latency feed logic
  - Portfolio-level optimization across multiple open pairs

## Stakeholders
- Operator: reviews, decides, executes, and confirms both legs.
- Quant/Risk owner: defines thresholds and validates reasons.
- Engineering: guarantees API/UI consistency and traceability.

## Roles and Ownership
- Backend domain layer owns lifecycle state (`candidate -> ... -> closed`) and gate outcomes.
- UI renders backend projections only and cannot derive business lifecycle transitions.
- Risk owner approves gate policy changes and auto-unwind thresholds.
- Operator is accountable for lifecycle confirmation (`mark_viewed`, `enter_submitted`, `enter_filled`, `entry_cancelled`, `exit_filled`, `confirm_followup`, `manual_override`) and comments.
- Source owners (TA/FA/News) are accountable for evidence freshness and quality metadata.

## Signal Composition Across Sources
- Each source publishes normalized evidence item with stance: `support`, `oppose`, or `neutral`.
- Composer aggregates evidence per entity and computes conflict summary (`support_weight`, `oppose_weight`, `veto`).
- Policy engine maps evidence summary to actionability:
  - `allow`: entry/exit can be actionable.
  - `reduce`: actionable with risk-size reduction.
  - `review`: visible but requires manual confirmation.
  - `block`: delivery suppressed with explicit reason.
- High-severity contradictory news can veto entry even when technical/fundamental sources support it.

## Policy Precedence Matrix (Planned)
Final policy decision is deterministic and resolved by ordered gates:

| Priority | Gate | `block` effect | `review` effect | `reduce` effect |
|---|---|---|---|---|
| 1 | `risk_profile` | `blocked_entry` | `review_entry` | `actionable_enter` with reduced size |
| 2 | `news_geopolitics` | `blocked_entry` | `review_entry` | `actionable_enter` with reduced size |
| 3 | `liquidity` | `blocked_entry` | `review_entry` | `actionable_enter` with reduced size |
| 4 | `execution_feasibility` | `enter_out_of_range` or `blocked_entry` | `review_entry` | `actionable_enter` with narrower limits |
| 5 | `source_freshness` | `blocked_entry` | `review_entry` | `actionable_enter` with confidence penalty |
| 6 | `portfolio_limits` | `blocked_entry` | `review_entry` | `actionable_enter` with capped exposure |
| 7 | `venue_constraints` | `blocked_entry` | `review_entry` | `actionable_enter` with operational limits |

Decision rule:
- Any `block` at any gate -> final policy `block`.
- Else any `review` -> final policy `review`.
- Else any `reduce` -> final policy `reduce`.
- Else final policy `allow`.

## SLA and Escalation
- SLA-1: actionability projection refresh <= 60 seconds from latest signal cycle.
- SLA-2: pretrade response <= 10 seconds under normal ISS transport conditions.
- SLA-3: action audit persistence is write-through and must not drop events.
- Escalation-1: if pretrade cannot be confirmed for 2 consecutive checks, set lifecycle to `blocked` and alert operator.
- Escalation-2: if one-leg execution remains unmatched beyond policy timeout, trigger auto-unwind policy evaluation.
- Escalation-3: if ISS transport degrades, execution mode stays fail-closed unless explicit privileged override is logged.

## Preconditions
- Fresh signal cycle exists (`signal_runs` + `signal_history` populated).
- Pair has strategy output fields (`signal_action`, `signal_metrics`).
- Operator has terminal access for mandatory manual quote confirmation.

## Main Flow
| Stage | Operator Action | System Behavior | Record of Fact |
|---|---|---|---|
| 0. Morning Health-check | Receive daily bot status message | Worker checks backend availability and active signals count, then sends one summary per day per chat | Telegram heartbeat message + worker state (`daily_healthcheck_last_sent_date_by_chat`) |
| 1. Discover | Open `Signals`, apply filters | Load active/history signals with backend lifecycle projection | `signal_history` rows visible in UI |
| 2. Candidate Review | Pick a pair with entry intent | Show entry corridors, risk levels, forecast horizon | `signal_metrics` fields (`entry_*`, `tp/sl_*`, `forecast_*`) |
| 3. Pre-trade Check | Trigger `Refresh pre-trade` if needed | Call `/api/pretrade/check`, evaluate two-leg gates, return `ready_to_place` | Pre-trade payload (`status`, `gates`, `hits`, `reasons`) |
| 4. Entry Decision | Compare app output with terminal quotes | Read backend lifecycle (`ready|blocked|hold_open|exit_ready`) and gate reasons | Effective status in main `Signal` column |
| 4a. Telegram Review | Press `Mark viewed` in Telegram | Worker posts canonical `action=mark_viewed` to the v2 pair/entity action API (`ack` stays alias-only for compatibility) | `signal_executions` row with `action=mark_viewed`, `status=viewed`, note metadata |
| 5. Entry Execution | Submit both legs manually | Allow `Execute` only when entry is not pre-trade blocked; persist `enter_submitted` first and `enter_filled` only after actual fill | `signal_executions` rows with lifecycle actions `enter_submitted` / `enter_filled` |
| 6. Active Monitoring | Re-open details for open/flat pair with pending intent | Keep pair visible and, when last `enter` intent was not explicitly used, promote pending intent back to actionable `enter` within TTL | New `signal_history` rows + pending intent projection in `/api/v2/signals/active` |
| 6a. Delivery State | Review delivery flags in UI/API/Telegram | Use shared delivery fields (`delivery_allowed`, `entry_signal_expired`, `entry_range_eligible`) to explain why signal is sent/suppressed | `/api/v2/signals/active` delivery fields + Telegram worker state |
| 7. Exit Trigger | React to `exit` signal and reason | Surface reason (`tp`, `sl`, `time`, `expiry`) and supporting metrics | Exit reason in `signal_reasons` / `signal_metrics` |
| 8. Exit Execution | Close both legs manually | Persist exit lifecycle action with explicit H4A exit reason and update actionable view | `signal_executions` rows with action `exit_filled` |
| 9. Audit | Review full lifecycle for pair | Provide history of signals + executions for replay | `signal_history` + `signal_executions` |

## H4A Baseline Addendum
- Current morning futures manual execution baseline: `H4A_CAP_OFF`.
- The generic flow above is not sufficient by itself for `H4A`.
- `O1` is kept only as the reference baseline; live execution must be read as `H4A_CAP_OFF`.
- Operators must follow [H4A Manual Execution Baseline](runbooks/h4a-manual-execution-baseline.md) whenever the signal is executed as the active morning futures baseline.
- Additional mandatory actions for `H4A`:
  - calculate planned `qty_lots` only from the `20_000 RUB` H4A risk budget before sending the order,
  - start a `10`-minute timer on every LIMIT entry and replace the order if it is still not filled,
  - recalculate effective TP and stop from the realized fill,
  - manage break-even and trailing stop updates after fill,
  - force a `180`-minute time exit if the position is still open,
  - record whether stop-based exit was `initial_loss_sl` or `protective_sl`,
  - record `same_bar_resolution` or `same_bar_ambiguous` when broker/exchange sequencing cannot be reconstructed,
  - use Telegram follow-up for fallback timeout, post-fill packet, break-even/trailing triggers, time-stop reminder, explicit `Confirm`, and explicit `Manual override`.
- If the operator intentionally skips any of these rules, the trade must be logged as a manual override rather than a baseline `H4A` execution.

## Target Entity-Centric Lifecycle
This lifecycle is the contract model for `/api/v2/signals/actionability` and Telegram worker unification.

| State | Meaning for operator | UI behavior | Telegram behavior | Exit condition |
|---|---|---|---|---|
| `actionable_enter` | Entity can be used now with current bounds | Show entity with entry corridor | Send `enter` once per `intent_id`/fingerprint (cooldown-aware) | Explicit usage, expiry, out-of-range, policy downgrade |
| `review_entry` | Sources/gates conflict, manual confirmation required | Show visible but non-auto-executable state with reasons | No normal enter push (optional review alert only) | Manual decision or policy becomes `allow/reduce/block` |
| `enter_out_of_range` | Entry idea tracked, but market moved out of corridor | Keep row visible as non-actionable context | Send one out-of-range update for current fingerprint | Reprice to new bounds or expire |
| `actionable_enter_repriced` | Recomputed bounds restored executable entry | Show updated plan revision | Send new enter update only for new fingerprint/revision | Explicit usage, expiry, out-of-range again |
| `hold_open` | Operator explicitly entered and position is open | Show hold overlay with execution facts | Send H4A follow-up packet, require stage confirmations, and send monitor reminders when baseline mode is active | Exit signal + manual exit |
| `actionable_exit` | Open position can be closed by strategy | Show exit actionable | Send exit notification | Explicit exit execution |
| `blocked_entry` | Deterministic gate/policy blocks entry | Keep entity visible with blocking reason | Enter delivery suppressed | Gate clears or new intent revision appears |
| `inactive` | No active intent/action for now | Hide by default unless non-actionable filter enabled | No delivery | New independent setup appears |

Lifecycle composition rule:
- `position_state` (`flat/open`) is independent from `intent_state` and policy.
- `hold_open` is an overlay from execution ledger, not a replacement for entry eligibility.
- `actionability_state` is a derived UI label over axes: policy, intent, position, execution, delivery.
- `operator_signal_status` is derived from the operator execution ledger and can be reconstructed from fingerprint or pair-level legacy notes.

### After `ENTER_OUT_OF_RANGE`
- Entity does not disappear immediately from projection.
- System recalculates executable entry bounds on each refresh cycle from latest market snapshot.
- Worker sends exactly one out-of-range notification per fingerprint and does not spam on repeated out-of-range cycles.
- If recalculated bounds become executable again, projection switches to `actionable_enter_repriced` with a new plan revision/fingerprint.
- If intent TTL ends before repricing returns to executable state, intent becomes `expired` and delivery remains suppressed.

### H4A Follow-Up Lifecycle
- `enter_submitted` keeps the intent visible but does not consume it into `hold_open`.
- When the LIMIT timer reaches `10` minutes without fill, the system marks `entry_fallback_due` and sends a Telegram reminder to replace the order or record deviation.
- Only `enter_filled` creates `hold_open` and opens the post-fill monitoring lifecycle.
- Post-fill Telegram flow is staged:
  - post-fill packet with recalculated bracket,
  - break-even or trailing trigger reminder when market reaches the activation threshold,
  - time-stop reminder,
  - overdue time-stop alert,
  - explicit `Confirm` action for each completed H4A operator step,
  - explicit `Manual override` action for deviations from H4A.
- `confirm_followup` is audit-only: it records Telegram/operator confirmation for the current H4A stage and does not consume intent, open a position, or replace `enter_filled`.

## User Stories and Acceptance

### US-SIG-01 Review actionability before opening details
- As an operator, I want the top-level signal status to already include pre-trade constraints.
- Acceptance:
  - `Signal` column shows `enter`, `hold_pretrade`, `check_pretrade`, `hold_open`, or `exit`.
  - Entry rows without pre-trade payload are not shown as final `enter`.

### US-SIG-02 Validate two-leg entry readiness
- As an operator, I want deterministic pre-trade checks for both legs and spread consistency.
- Acceptance:
  - `/api/pretrade/check` returns `ready_to_place`, `gates`, `hits`, `reasons`.
  - Missing quote on either leg keeps entry blocked.
  - `manual_confirm_required` remains true in ISS delayed mode.

### US-SIG-03 Execute entry with traceability
- As an operator, I want each execution step captured for later audit.
- Acceptance:
  - Entry `Execute` writes a row to `signal_executions`.
  - Stored fields include pair, direction, action, price, quantity, side, order_id, note, timestamp.
  - For two-leg execution, both legs can be linked by one `order_id`; one-leg execution remains valid with a single row.

### US-SIG-04 Monitor open position until exit condition
- As an operator, I want clear transition from monitoring to exit-ready behavior.
- Acceptance:
  - If a pair has an open position (entered and not closed), it remains visible in `Signals` with explicit status `hold_open` until closure.
  - Ongoing refresh updates reasons/metrics in `signal_history`.
  - Exit rationale is visible in details and not hidden in raw payload only.

### US-SIG-05 Close position and complete lifecycle
- As an operator, I want clean closure with both-leg accountability.
- Acceptance:
  - Exit action is logged in `signal_executions`.
  - Pair is no longer shown as actionable `exit` after closure.

### US-SIG-06 Confirm signal review from Telegram
- As an operator, I want to mark in Telegram that I reviewed the signal, then record order/fill details separately.
- Acceptance:
  - Telegram inline button stores canonical `action=mark_viewed`; legacy `ack` is accepted only as an alias.
  - Reviewing a signal keeps entry actionable while the intent is still valid.
  - `signal_details_pending=true` remains until explicit `enter_filled` or `entry_cancelled`.
  - Review action does not alter open position balance (`enter_filled` / `exit_filled` math only).

### US-SIG-07 Daily bot liveness and data check
- As an operator, I want one morning message confirming that bot polling is alive and backend data is reachable.
- Acceptance:
  - Worker sends one daily health-check per registered chat after configured local time (`daily_healthcheck_time_local`).
  - Message includes bot status, backend status, and active signals count.
  - If backend is unavailable, message is still sent with `Backend: ERROR`.

### US-SIG-08 Keep entry actionable until explicit usage
- As an operator, I want to keep receiving `enter` opportunity while it is still valid, even if strategy row moved to `hold`.
- Acceptance:
  - Entity remains visible as `actionable_enter` while current bounds are executable and intent is not consumed.
  - Actionability is entity-centric (by `entity_ref` + `intent_id`), not hard-coupled to one historical `signal_id`.
  - `mark_viewed` does not suppress delivery by itself.
  - Suppression starts only after explicit execution progression (`enter_submitted`, `enter_filled`, `entry_cancelled`, or `manual_override`).

### US-SIG-09 Notify when sent entry leaves planned corridor
- As an operator, I want a single Telegram update if already-sent entry becomes non-executable due to price drift.
- Acceptance:
  - Worker tracks baseline entry corridor for sent `enter`.
  - On first out-of-range transition worker sends one update with current vs baseline bounds.
  - Repeated out-of-range cycles for same fingerprint do not spam chat.
  - If repricing creates a new executable plan revision, worker may send one new `enter` update for that new fingerprint.

### US-SIG-10 Resolve contradictory multi-source evidence deterministically
- As an operator, I want contradictory TA/FA/news evidence to be resolved with explicit deterministic policy output.
- Acceptance:
  - Projection exposes `policy_outcome.status` in `allow|reduce|review|block`.
  - Projection includes ordered gate trace with reasons and priorities.
  - High-severity news veto can block entry even when TA/FA support it, with visible reason codes.
  - `review` state remains visible and requires explicit operator confirmation before execution.

## Alternative and Exception Flows

### AF-01 Pre-trade endpoint unavailable (e.g., 404)
- Behavior:
  - Effective action for entry remains `check_pretrade`.
  - Entry execution is blocked until successful check.

### AF-02 Futures quote/depth missing in ISS snapshot
- Behavior:
  - Pre-trade returns reasons like `fut_quote_missing`.
  - Effective action may still allow entry in ISS manual-drive mode.
  - Futures diagnostics remain visible for manual terminal verification.

### AF-03 Snapshot desync or spread outside corridor
- Behavior:
  - Pre-trade returns `snapshot_unsynced` or `spread_out_of_band`.
  - Entry remains blocked.

### AF-04 One leg executed, second leg pending (operational risk)
- Policy-driven behavior:
  - Start `auto-unwind` timer as soon as leg imbalance is detected.
  - If second leg is not confirmed before timeout, submit `CLOSE` action with reason `LEG_IMBALANCE_TIMEOUT`.
  - Execute policy via `POST /api/v2/policies/auto-unwind/run` (`dry_run` before live mode).
  - Keep full audit in decision actions and execution events.

### AF-05 Telegram review token expired or already consumed
- Behavior:
  - Worker rejects callback token and notifies user.
  - No duplicate `mark_viewed` record is written.

### AF-06 Backend unavailable during daily health-check
- Behavior:
  - Worker catches backend error while reading `/api/signals/active`.
  - Health-check message is still delivered with degraded status (`Backend: ERROR`).

### AF-07 Sent entry moved outside original corridor
- Behavior:
  - Worker keeps first sent baseline bounds for `enter` fingerprint.
  - If current prices leave baseline corridor, worker sends one update and marks fingerprint as out-of-range notified.
  - Entity remains in projection with state `enter_out_of_range` and is recalculated each cycle.
  - New `enter` fingerprint for same entity still respects entity-level cooldown.

## Traceability Matrix
| Requirement | UI | API | Persistence | Evidence |
|---|---|---|---|---|
| Effective signal with pre-trade constraints | `signals` table `signal_action_effective` | `/api/v2/signals/active`, `/api/v2/pretrade/check` | `signal_history` + backend gate projection | Visible status and details block |
| Two-leg pre-trade validation | `Pre-trade` panel | `/api/pretrade/check` | Not persisted server-side as a separate table | `status/gates/hits/reasons` payload |
| Entry execution logging | `Execute signal` form | `POST /api/v2/signals/{signal_id}/actions` (v1 adapter: `POST /api/signals/execute`) | `signal_executions` | Execution history table |
| Fail-closed execution control | `Execute signal` response messaging | `POST /api/v2/signals/{signal_id}/actions` | `signal_executions.note` (override metadata) | `status=blocked` with reason code or audited override |
| Telegram review traceability | Telegram inline button + `Signals` flags | `POST /api/v2/entities/{entity_type}/{entity_id}/signals/actions` (`action=mark_viewed`, `ack` alias), `GET /api/v2/signals/active` | `signal_executions.note` + derived flags | `signal_viewed*`, `signal_details_pending`, `operator_signal_status` |
| Telegram daily health-check | Telegram bot chat | Telegram Bot API `sendMessage` + backend `GET /api/v2/signals/active` | worker state (`daily_healthcheck_last_sent_date_by_chat`) | One morning message per chat with backend/data status |
| Pending entry lifecycle projection | Signals table + Telegram worker | `GET /api/v2/signals/active` | `signal_history` + explicit action notes | `signal_origin_*`, `pending_entry_intent_active`, delivery fields |
| Entry drift notification without spam | Telegram bot chat | Telegram Bot API `sendMessage` + backend `GET /api/v2/signals/active` | worker state (`enter_tracking_by_fingerprint`, `enter_last_sent_at_by_pair`) | One out-of-range update per fingerprint |
| Pair-centric actionable projection | Signals table + Telegram worker | `GET /api/v2/pairs/actionability` | `signal_history` + `signal_executions` + delivery state | `actionable_enter`, `hold_open`, `actionable_exit`, `enter_out_of_range` |
| Entity-centric actionable projection | Signals table + Telegram worker | `GET /api/v2/signals/actionability` | evidence composition + signal/action ledger | pair and instrument actionability with policy/veto transparency |
| Policy precedence and conflict audit | Signal details + API consumer logs | `GET /api/v2/signals/actionability` | ordered gate evaluation trace | `policy_outcome.precedence_version`, `gate_trace`, deterministic `allow/reduce/review/block` |
| Pair-level action API | Signals UI + Telegram callbacks | `POST /api/v2/pairs/{pair_id}/actions` | pair intent + action execution log | intent-aware `mark_viewed`, `enter_submitted`, `enter_filled`, `entry_cancelled`, `exit_submitted`, `exit_filled`, `confirm_followup`, `manual_override` traceability |
| Entity-level action API | Signals UI + Telegram callbacks | `POST /api/v2/entities/{entity_type}/{entity_id}/signals/actions` | canonical action ledger | idempotent lifecycle actions for pair and instrument, including audit-only `confirm_followup` |
| Exit reason transparency | Signal details (`Context`, `Risk`, `Forecast`) | `/api/signals/active`, `/api/signals/history` | `signal_history.metrics/reasons` | Reason codes (`tp/sl/time/expiry`) |
| Leg imbalance remediation | Signal monitoring + ops controls | `POST /api/v2/policies/auto-unwind/run` | `signal_executions` | Auto-generated `exit` with `LEG_IMBALANCE_TIMEOUT` |
| Lifecycle auditability | History + details | `/api/v2/decisions/{decision_id}/actions`, `/api/signals/executions` | `signal_history` + `signal_executions` + decision actions | Pair replay from first entry to final exit |

## MVP vs Next

### MVP (must keep)
- Effective signal status that includes pre-trade outcome.
- Deterministic pre-trade gate with explicit blocking and advisory reasons.
- Mandatory manual confirmation in ISS delayed mode.
- Entry/exit execution logging with pair-level history.

Implemented policy note:
- Current ISS mode uses stock-leg blocking gates for `ready_to_place`.
- Futures/spread/sync gates are computed as advisory diagnostics and do not block execution.

### Next (recommended)
- Exit-side pre-trade check symmetry (not only entry-side).
- Alerting channel for exit urgency and stale-data risk.
- Persisted pre-trade check snapshots for compliance-grade replay.

## Open Decisions
- Should pre-trade payload be persisted server-side for every check?
- Should exit action also be gated by dedicated two-leg executable corridor checks?
- Should auto-unwind timeout vary by liquidity regime and instrument class?
