# Signals Tab Business Process (Stock/Futures Spread, ISS Delayed Mode)

## Purpose
Define an end-to-end operator process in `Signals` from entry decision to exit execution for two-leg stock/futures trades under ISS delayed data constraints.

## Scope
- Included:
  - Signal review and filtering in `Signals`
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

## Preconditions
- Fresh signal cycle exists (`signal_runs` + `signal_history` populated).
- Pair has strategy output fields (`signal_action`, `signal_metrics`).
- Operator has terminal access for mandatory manual quote confirmation.

## Main Flow
| Stage | Operator Action | System Behavior | Record of Fact |
|---|---|---|---|
| 0. Morning Health-check | Receive daily bot status message | Worker checks backend availability and active signals count, then sends one summary per day per chat | Telegram heartbeat message + worker state (`daily_healthcheck_last_sent_date_by_chat`) |
| 1. Discover | Open `Signals`, apply filters | Load active/history signals and compute `signal_action_effective` | `signal_history` rows visible in UI |
| 2. Candidate Review | Pick a pair with entry intent | Show entry corridors, risk levels, forecast horizon | `signal_metrics` fields (`entry_*`, `tp/sl_*`, `forecast_*`) |
| 3. Pre-trade Check | Trigger `Refresh pre-trade` if needed | Call `/api/pretrade/check`, evaluate two-leg gates, return `ready_to_place` | Pre-trade payload (`status`, `gates`, `hits`, `reasons`) |
| 4. Entry Decision | Compare app output with terminal quotes | Resolve effective action: `enter` or `hold_pretrade` or `check_pretrade` | Effective status in main `Signal` column |
| 4a. Telegram ACK | Press `Use signal` in Telegram | Worker posts `action=ack` to `/api/signals/execute` | `signal_executions` row with `action=ack`, `status=acknowledged`, note metadata |
| 5. Entry Execution | Submit both legs manually | Allow `Execute` only when entry is not pre-trade blocked | `signal_executions` rows with action `enter` |
| 6. Active Monitoring | Re-open details for open pair | Keep open pair visible in `Signals` and show risk/forecast/model checks/new updates | New `signal_history` rows per cycle + `signal_executions` open state |
| 7. Exit Trigger | React to `exit` signal and reason | Surface reason (`tp`, `sl`, `time`, `expiry`) and supporting metrics | Exit reason in `signal_reasons` / `signal_metrics` |
| 8. Exit Execution | Close both legs manually | Persist exit action and update actionable view | `signal_executions` rows with action `exit` |
| 9. Audit | Review full lifecycle for pair | Provide history of signals + executions for replay | `signal_history` + `signal_executions` |

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

### US-SIG-06 Confirm signal usage from Telegram
- As an operator, I want to mark in Telegram that I used the signal, then add trade details in UI.
- Acceptance:
  - Telegram inline button stores `action=ack` with `status=acknowledged`.
  - `/api/signals/active` sets `signal_used=true` for the acknowledged signal.
  - `signal_details_pending=true` remains until first `enter/exit` appears after ACK for the pair.
  - ACK does not alter open position balance (`enter/exit` math only).

### US-SIG-07 Daily bot liveness and data check
- As an operator, I want one morning message confirming that bot polling is alive and backend data is reachable.
- Acceptance:
  - Worker sends one daily health-check per registered chat after configured local time (`daily_healthcheck_time_local`).
  - Message includes bot status, backend status, and active signals count.
  - If backend is unavailable, message is still sent with `Backend: ERROR`.

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
- Current process:
  - Must be handled by operator procedure via execution notes and immediate follow-up action.
- Gap:
  - No automated unwind workflow in current `Signals` flow.

### AF-05 Telegram ACK token expired or already consumed
- Behavior:
  - Worker rejects callback token and notifies user.
  - No duplicate ACK record is written.

### AF-06 Backend unavailable during daily health-check
- Behavior:
  - Worker catches backend error while reading `/api/signals/active`.
  - Health-check message is still delivered with degraded status (`Backend: ERROR`).

## Traceability Matrix
| Requirement | UI | API | Persistence | Evidence |
|---|---|---|---|---|
| Effective signal with pre-trade constraints | `signals` table `signal_action_effective` | `/api/signals/active`, `/api/pretrade/check` | `signal_history` + transient pre-trade cache in UI state | Visible status and details block |
| Two-leg pre-trade validation | `Pre-trade` panel | `/api/pretrade/check` | Not persisted server-side as a separate table | `status/gates/hits/reasons` payload |
| Entry execution logging | `Execute signal` form | `POST /api/signals/execute` | `signal_executions` | Execution history table |
| Telegram ACK traceability | Telegram inline button + `Signals` flags | `POST /api/signals/execute` (`action=ack`), `GET /api/signals/active` | `signal_executions.note` + derived flags | `signal_used*`, `signal_details_pending` |
| Telegram daily health-check | Telegram bot chat | Telegram Bot API `sendMessage` + backend `GET /api/signals/active` | worker state (`daily_healthcheck_last_sent_date_by_chat`) | One morning message per chat with backend/data status |
| Exit reason transparency | Signal details (`Context`, `Risk`, `Forecast`) | `/api/signals/active`, `/api/signals/history` | `signal_history.metrics/reasons` | Reason codes (`tp/sl/time/expiry`) |
| Lifecycle auditability | History + details | `/api/signals/history`, `/api/signals/executions` | `signal_history` + `signal_executions` | Pair replay from first entry to final exit |

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
- Automated leg-risk control when one leg fills and second does not.
- Exit-side pre-trade check symmetry (not only entry-side).
- Alerting channel for exit urgency and stale-data risk.
- Persisted pre-trade check snapshots for compliance-grade replay.

## Open Decisions
- Should pre-trade payload be persisted server-side for every check?
- Should exit action also be gated by dedicated two-leg executable corridor checks?
