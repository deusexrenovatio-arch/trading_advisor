# PreTrade Delay Gate v1 (ISS REST, no auth)

## Scope
Defines pre-trade readiness checks for stock-futures spread entries when market data comes from MOEX ISS REST with delayed quotes.

Objective:
- confirm that both legs had executable price presence in the required range, even with delay;
- keep manual broker-side verification mandatory before order placement.

## Constraints (ISS REST without auth)
- Quote delay is approximately 15 minutes in practice.
- Futures `BID/OFFER` may be missing in `marketdata` even for active contracts.
- This gate cannot guarantee real-time depth or immediate fill quality.

## Statuses (operator-facing)
- `WAIT`: no actionable candidate or stale/invalid context.
- `CHECK`: candidate exists; wait for gate pass/fail reason breakdown.
- `PLACE`: gate passes for both legs and spread check in delayed mode; manual confirm still required.
- `EXECUTING`: one leg filled, second leg pending; timeout/unwind policy applies.
- `OPEN`: both legs filled and position is active.

## Inputs
Per pair:
- `stock`, `future`, `direction` (`cash_and_carry` or `reverse`)
- target prices from signal snapshot: `spot_target`, `fut_target`, `spread_target`
- delayed snapshots window size `N`

Per snapshot (from ISS `marketdata`):
- stock: `BID`, `OFFER`, `LAST`, `NUMTRADES`, `SYSTIME`
- future: `BID`, `OFFER`, `LAST`, `NUMTRADES`, `SYSTIME`

API integration:
- `GET /api/pretrade/check?stock=...&future=...`
- optional params: `snapshots`, `min_hits`, `eps`, `sync_sec`, `poll_sec`, `qty_fut`, `participation_rate`
- returns: `status`, `ready_to_place`, `reasons`, `order_price_bands`, `volume_requirements`, per-gate `hits`.

## Parameters
- `N`: number of delayed snapshots (default 4)
- `min_hits`: minimum positive hits for leg pass (default 2)
- `eps`: per-leg price tolerance from target (default `spread_carry_alpha.entry_price_tolerance_pct`, baseline 0.0015 = 0.15%)
- `sync_sec`: max stock/future `SYSTIME` difference per snapshot (default 120 sec)
- `manual_confirm_required`: always `true` in ISS mode

## Deterministic checks
For `cash_and_carry`:
- stock buy range hit:
  - `OFFER <= spot_target * (1 + eps)`
- future sell range hit:
  - `BID >= fut_target * (1 - eps)`

For `reverse`:
- stock sell range hit:
  - `BID >= spot_target * (1 - eps)`
- future buy range hit:
  - `OFFER <= fut_target * (1 + eps)`

Shared:
- `leg_pass = hits_in_window >= min_hits`
- `sync_pass = sync_hits >= min_hits`, where `|SYSTIME_stock - SYSTIME_fut| <= sync_sec`
- delayed spread consistency:
  - compute executable worst spread per direction from available `BID/OFFER`
  - `spread_pass = spread_hits >= min_hits`
- quote availability gate:
  - `stock_quote_pass = stock_quote_hits >= min_hits`
  - `fut_quote_pass = fut_quote_hits >= min_hits`
  - `quote_pass = stock_quote_pass && fut_quote_pass`
- final:
  - volume gate:
    - `stock_volume_pass = stock_volume_hits >= min_hits`
    - `fut_volume_pass = fut_volume_hits >= min_hits`
  - `ready_to_place = quote_pass && stock_leg_pass && fut_leg_pass && sync_pass && spread_pass && stock_volume_pass && fut_volume_pass`
  - `manual_confirm_required = true`

## Decision mapping
- if no candidate -> `WAIT`
- if candidate and `ready_to_place=false` -> `CHECK` with reasons:
  - `stock_quote_missing`
  - `fut_quote_missing`
  - `stock_range_miss`
  - `fut_range_miss`
  - `snapshot_unsynced`
  - `spread_out_of_band`
- if candidate and `ready_to_place=true` -> `PLACE`

## Live validation (MOEX ISS REST, 2026-02-09)
Validation time:
- around `2026-02-09 16:40-16:44 MSK`
- source: live ISS REST `marketdata`

Sample:
- candidate pairs observed: `AFLT/AFH6`, `AFLT/AFM6`, `AFKS/AKH6`, `ALRS/ALH6`

Scenario (strict):
- params: `N=4`, `min_hits=2`, `eps=0.15%`, `sync_sec=120`
- result: `ready_to_place = 0/4`
- main fail reason: `fut_quote_missing` and `fut_range_miss`
- observation: futures `BID/OFFER` were missing in ISS snapshots.

## Operational recommendation (ISS-only mode)
- Keep `manual_confirm_required=true`.
- Use strict quote gating as default even in ISS-only mode.
- If futures quote is absent in ISS, do not place by signal and keep manual terminal verification as the only source of actionable price.
- When real-time feed becomes available, keep the same strict policy and tighten orderbook checks by both legs.
