# News Golden Events v1 (Manual)

Date: 2026-03-05  
Source set: internet news URLs + local `data/news_livecheck_ng.db` verification metrics.

## Scope
- Commodity set in active news contour: `BRN`, `NG_US`, `GOLD`.
- Manual selection size: 30 events (10 per commodity).
- Artifact CSV: `docs/research/news_golden_events_v1.csv`.

## Selection Rules
- Root-cause first: picked news that describes mechanism/cause (closure, strike, outage, rate path, safe-haven trigger), not pure market recap.
- Price effect confirmed: `verified_move_1h` or `verified_move_1d` is true, with non-trivial `max_abs_z_1d`.
- Post-effect evidence: non-zero `post_effect_news_count_24h`.
- Source sanity: internet URLs checked from mainstream/business outlets; mirror spam and obvious off-topic pages removed.

## Why this set
- It is intentionally compact and manual, to calibrate classification quality first.
- It includes the missing class around 2026-02-28 Iran strike chain as explicit root-cause samples.
- It provides broad mechanism coverage for tuning:
  - `BRN`: chokepoint closure/reopen, shipment suspension, facility-attack risk.
  - `NG_US`: LNG route disruptions, Hormuz transmission, LNG outage shock.
  - `GOLD`: safe-haven demand, USD/rate-path offset, policy repricing.

## Immediate Tuning Targets
1. Reduce over-generic `middle_east_supply_risk` assignments.
2. Promote strike/facility-attack headlines to route-aware outage classes when exporter/entity evidence exists.
3. Improve GOLD cause extraction on hyphenated safe-haven and Fed/rate phrasing.

## Notes
- This v1 file is a calibration baseline, not a final benchmark.
- After rule updates, the same 30 rows should be replayed to measure precision gain and missed-root reduction.
