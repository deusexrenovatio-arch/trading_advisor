# Execution Profiles Historical Review (2020-2026)

Date: 2026-03-06

## Scope
- Objective: extend the execution-profile comparison beyond the original `2025-2026` ladder window and check whether `O1`, `H3B_SL_3P0`, and `H4A_CAP_OFF` stay economically coherent on older market regimes.
- Profiles:
  - `O1`: accepted runtime baseline.
  - `H3B_SL_3P0`: wider stop at `3.0R`.
  - `H4A_CAP_OFF`: disable RR profit cap (`max_profit_rr=0.0`).
- Reference artifact:
  - `artifacts/research/wf_goal_v6_h24_causal_rerun_execution_fixed_O1_limitfallback10m1t_frontnearest_seed124_20260305.json`
- Historical review artifact:
  - `artifacts/research/wf_goal_v6_execution_profiles_historical_review_2020_2026_20260306.json`

## Data Coverage
- Historical prefetch `2020-2022`:
  - artifact: `artifacts/research/wf_goal_v6_historical_front_contract_prefetch_2020_2022_20260306.json`
  - active `SECID`: `264`
  - active roots: `15`
- Historical prefetch `2023-2024`:
  - artifact: `artifacts/research/wf_goal_v6_historical_front_contract_prefetch_2023_2024_20260306.json`
  - active `SECID`: `360`
  - active roots: `27`
- Review universe after union of reference contracts and historical active `SECID`:
  - instruments passed to review runner: `579`
  - first filled trade date: `2020-01-09`
  - last filled trade date: `2026-02-24`
  - filled trades for each profile: `954`

## 2020-2024 Robustness
This is the strict regime-stability slice requested for old regimes.

| Profile | Filled trades | Net ticks | Delta vs O1 | Expectancy net | Win rate net | Active months | Profitable months | Losing months | Flat months (`2020-01..2024-12`) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `O1` | 730 | 77,426.5 | 0.0 | 106.06 | 0.9466 | 59 | 56 | 3 | 1 |
| `H3B_SL_3P0` | 730 | 89,956.5 | 12,530.0 | 123.23 | 0.9479 | 59 | 56 | 3 | 1 |
| `H4A_CAP_OFF` | 730 | 119,588.5 | 42,162.0 | 163.82 | 0.9466 | 59 | 56 | 3 | 1 |

Observations:
- All three profiles stay profitable on every full year from `2020` through `2024`.
- `H3` beats `O1` on this slice, but the uplift is much smaller than `H4`.
- `H4` dominates `O1` on the same trade count and same window; the gain is expectancy-driven, not fill-count-driven.
- Full-calendar flat month on this slice: `2020-05`.

### Yearly Net Ticks (2020-2024)

| Year | `O1` | `H3B_SL_3P0` | Delta H3 vs O1 | `H4A_CAP_OFF` | Delta H4 vs O1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `2020` | 26,059.0 | 29,685.0 | 3,626.0 | 39,092.5 | 13,033.5 |
| `2021` | 17,866.0 | 22,492.5 | 4,626.5 | 28,201.5 | 10,335.5 |
| `2022` | 15,953.0 | 19,115.5 | 3,162.5 | 26,562.0 | 10,609.0 |
| `2023` | 11,125.0 | 11,360.5 | 235.5 | 16,397.5 | 5,272.5 |
| `2024` | 6,423.5 | 7,303.0 | 879.5 | 9,335.0 | 2,911.5 |

## Whole-Universe Result (2020-2026)

| Profile | Filled trades | Net ticks | Delta vs O1 | Expectancy net | Win rate net | Active months | Profitable months | Losing months | Flat months (`2020-01..2026-02`) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `O1` | 954 | 87,946.5 | 0.0 | 92.19 | 0.9444 | 72 | 68 | 4 | 2 |
| `H3B_SL_3P0` | 954 | 100,792.5 | 12,846.0 | 105.65 | 0.9444 | 72 | 68 | 4 | 2 |
| `H4A_CAP_OFF` | 954 | 135,521.5 | 47,575.0 | 142.06 | 0.9444 | 72 | 68 | 4 | 2 |

Observations:
- `H4` beats `O1` in every calendar year from `2020` through `2026`.
- `H3` also beats `O1`, but the incremental value is much smaller and fades after the older stress years.
- Full-calendar flat months in the completed period `2020-01..2026-02`: `2020-05`, `2025-01`.
- If the partial month `2026-03` is included, it is another flat month with no fills.

## Calendar Slice

### Active-Month View
This view counts only months with at least one filled trade.

| Profile | Active months | Profitable | Losing | Best month | Best net | Worst month | Worst net | Min | Max | Range | Median |
| --- | ---: | ---: | ---: | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| `O1` | 72 | 68 | 4 | `2022-03` | 13,335.5 | `2022-02` | -3,150.5 | -3,150.5 | 13,335.5 | 16,486.0 | 457.75 |
| `H3B_SL_3P0` | 72 | 68 | 4 | `2022-03` | 14,719.5 | `2022-02` | -2,493.5 | -2,493.5 | 14,719.5 | 17,213.0 | 538.0 |
| `H4A_CAP_OFF` | 72 | 68 | 4 | `2022-03` | 18,899.5 | `2025-02` | -1,331.5 | -1,331.5 | 18,899.5 | 20,231.0 | 690.75 |

### Losing Months
The same four losing months appear in all three profiles:
- `2021-02`
- `2021-08`
- `2022-02`
- `2025-02`

The difference is magnitude:
- `H4` materially reduces the depth of `2022-02` (`-1329.5` vs `-3150.5` in `O1`).
- `H3` improves `2022-02`, but worsens `2025-02` versus `O1`.

## Per-Instrument Assessment

### Main Structural Engines
These roots have both meaningful sample size and material contribution under `O1`.

| Root | Asset | Trades | Active months | `O1` net | H3 delta vs O1 | H4 delta vs O1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `PD` | `PLD` | 114 | 32 | 61,313.0 | 9,011.5 | 33,197.0 |
| `MM` | `MXI` | 84 | 25 | 7,381.0 | 799.5 | 4,649.5 |
| `RI` | `RTS` | 68 | 24 | 2,241.5 | 316.5 | 1,045.0 |
| `PT` | `PLT` | 98 | 26 | 2,223.5 | 185.5 | 1,127.5 |
| `GD` | `GOLD` | 58 | 22 | 1,820.5 | 285.5 | 895.5 |
| `NG` | `NG` | 85 | 24 | 1,800.5 | 286.5 | 805.5 |
| `MX` | `MIX` | 78 | 24 | 1,727.0 | 342.0 | 868.0 |
| `BR` | `BR` | 88 | 26 | 1,326.5 | 282.0 | 755.0 |

### Positive but Thin-Sample Instruments
These roots are profitable, but sample size is too thin for hard structural claims.

| Root | Asset | Trades | Active months | `O1` net | H4 delta vs O1 |
| --- | --- | ---: | ---: | ---: | ---: |
| `SX` | `STOX` | 18 | 3 | 1,796.0 | 1,273.0 |
| `N2` | `NIKK` | 10 | 3 | 1,233.0 | 457.5 |
| `SF` | `SPYF` | 11 | 5 | 328.5 | 252.5 |
| `CE` | `COPPER` | 15 | 4 | 279.0 | 72.0 |
| `S1` | `SILVM` | 10 | 2 | 250.0 | 145.5 |
| `BM` | `BRM` | 6 | 2 | 233.0 | 76.0 |
| `DX` | `DAX` | 15 | 5 | 189.5 | 124.5 |
| `SU` | `SUGAR` | 6 | 4 | 113.0 | 69.5 |
| `NR` | `NGM` | 8 | 2 | 67.5 | 39.0 |
| `FF` | `TTF` | 2 | 1 | 67.5 | 0.0 |
| `DJ` | `DJ30` | 3 | 1 | 63.0 | 66.0 |

### Positive but Secondary Contributors

| Root | Asset | Trades | Active months | `O1` net | H4 delta vs O1 |
| --- | --- | ---: | ---: | ---: | ---: |
| `HS` | `HANG` | 23 | 10 | 944.0 | 387.5 |
| `CC` | `COCOA` | 49 | 7 | 918.5 | 528.0 |
| `NA` | `NASD` | 29 | 12 | 593.5 | 210.0 |
| `SV` | `SILV` | 44 | 7 | 590.0 | 258.0 |
| `SA` | `SUGR` | 21 | 7 | 540.5 | 227.0 |

### Negative Watchlist
These roots remain negative even after `H4`; they are improved but not repaired.

| Root | Asset | Trades | Active months | `O1` net | `H3` net | `H4` net |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `AN` | `ALUM` | 4 | 1 | -45.0 | -52.0 | -28.5 |
| `KC` | `COFFEE` | 5 | 2 | -38.5 | -44.5 | -13.0 |
| `NC` | `NICKEL` | 2 | 1 | -10.0 | -9.0 | -6.0 |

### Breadth Check
- `2020-2024` subset:
  - active roots with fills: `18`
  - all `18` are profitable under `O1`, `H3`, and `H4`
  - `H4` improves all `18` roots versus `O1`
- full `2020-2026`:
  - active roots with fills: `27`
  - `O1` profitable roots: `24 / 27`
  - `H4` improves `26 / 27` roots and leaves `FF` unchanged
  - no root gets worse under `H4`

## No-Dominant-Top Diagnostic
The uplift is not only a `PD` story.

### Full `2020-2026`
- `O1` excluding `PD`: `26,633.5`
- `H3` excluding `PD`: `30,468.0`
- `H4` excluding `PD`: `41,011.5`

### Subset `2020-2024`
- `O1` excluding `PD`: `22,403.5`
- `H3` excluding `PD`: `26,805.0`
- `H4` excluding `PD`: `34,459.5`

## Conclusion
- The historical rerun is now valid: trades start in `2020`, not `2023`.
- `H4A_CAP_OFF` is the strongest economic profile on both:
  - the requested robustness slice `2020-2024`
  - the full whole-universe review `2020-2026`
- `H3B_SL_3P0` is directionally useful, but materially weaker than `H4`.
- The strategy is structurally carried by `PD`, but `H4` still wins after removing `PD`; the uplift is broad, not single-root-only.
- Instrument-level quality is not uniform: `AN`, `KC`, and `NC` remain negative watchlist roots, while several roots are positive but too thin-sampled for hard conclusions.
- Runtime baseline was not changed by this task; the result is research evidence for the next baseline decision.
