# Entity-Centric Signal Actionability v2

## Purpose
Define a deterministic architecture for actionable signals across multiple entity types and multiple evidence sources.

Supported entities:
- `pair` (stock+future)
- `instrument` (stock or future)

## Projection Model
One canonical row per entity in `GET /api/v2/signals/actionability`.

Core blocks:
- `entity_ref`: canonical identity.
- `evidence_items`: normalized source facts (`technical`, `fundamental`, `news`, `risk`, `liquidity`, ...).
- `evidence_summary`: support/oppose/conflict/veto aggregate.
- `policy_outcome`: deterministic gate result with precedence trace.
- `intent`: entry/exit intent lifecycle (`intent_id` + TTL + consumption).
- `axes`: explicit lifecycle axes (`policy_state`, `intent_state`, `position_state`, `execution_state`, `delivery_state`).
- `delivery`: anti-spam and suppression state for Telegram/UI.

`actionability_state` is a derived UI label over these blocks.

## Deterministic Gate Precedence (v1)
Ordered by priority:
1. `risk_profile`
2. `news_geopolitics`
3. `liquidity`
4. `execution_feasibility`
5. `source_freshness`
6. `portfolio_limits`
7. `venue_constraints`

Resolution rule:
- any `block` -> final `policy=block`
- else any `review` -> final `policy=review`
- else any `reduce` -> final `policy=reduce`
- else final `policy=allow`

## Lifecycle Axes
- `policy_state`: `allow|reduce|review|block`
- `intent_state`: `none|active|out_of_range|consumed|expired|superseded`
- `position_state`: `flat|open`
- `execution_state`: `in_range|out_of_range|not_applicable`
- `delivery_state`: `not_sent|sent|suppressed|out_of_range_notified|cooldown`

## Derived State Mapping
Examples:
- `actionable_enter`: policy in `allow|reduce`, intent `active`, execution `in_range`
- `review_entry`: policy `review`
- `enter_out_of_range`: intent `out_of_range` or execution `out_of_range`
- `actionable_enter_repriced`: new in-range plan revision after out-of-range state
- `blocked_entry`: policy `block`
- `hold_open`: position overlay from execution ledger
- `actionable_exit`: open position with valid exit intent
- `inactive`: no actionable intent

## Key Business Rules
- `hold_open` is derived only from execution facts, not from latest signal row text.
- Explicit operator action (`ack` or `enter`) consumes intent.
- Out-of-range does not remove entity from projection.
- Repricing creates a new revision/fingerprint and can produce one new enter notification.
- High-severity contradictory news can veto entry even with strong TA/FA support.

## Delivery Rules (Telegram)
- one enter message per fingerprint/revision;
- one out-of-range update per fingerprint;
- no repeated out-of-range spam;
- new enter message allowed only for new revision/fingerprint and cooldown pass.

## Canonical APIs
- Read projection: `GET /api/v2/signals/actionability`
- Execute action: `POST /api/v2/entities/{entity_type}/{entity_id}/signals/actions`

Compatibility adapters:
- `GET /api/v2/pairs/actionability`
- `POST /api/v2/pairs/{pair_id}/actions`
