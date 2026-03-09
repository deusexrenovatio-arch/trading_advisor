# Execution Profiles Historical Review Without Mini Contracts (2020-2026)

Date: 2026-03-06

## Scope
- Objective: remove duplicated mini-contract exposure from the historical execution-profile review and re-evaluate the baseline decision.
- Excluded mini roots:
  - `BM (Brent mini)` in favor of `BR (Brent)`
  - `GN (Gold mini)` in favor of `GD (Gold)`
  - `NR (Natural Gas mini)` in favor of `NG (Natural Gas)`
  - `RM (RTS mini)` in favor of `RI (RTS Index)`
  - `S1 (Silver mini)` in favor of `SV (Silver)`
- Source artifacts:
  - `artifacts/research/wf_goal_v6_execution_profiles_historical_review_2020_2026_20260306.json`
  - `artifacts/research/wf_goal_v6_execution_profiles_historical_review_no_minis_2020_2026_20260306.json`

## Baseline Decision
- `H4A_CAP_OFF` remains the strongest execution profile after mini exclusion.
- Promotion of `H4A_CAP_OFF` to runtime baseline is now supported by:
  - old-regime slice `2020-2024`
  - full whole-universe review `2020-2026`
  - no-mini universe hygiene
  - broad per-root uplift rather than a single-root-only effect

## Summary After Mini Exclusion

| Profile | Filled trades | Net ticks (`2020-2026`) | Delta vs O1 | Expectancy net | Win rate net |
| --- | ---: | ---: | ---: | ---: | ---: |
| `O1` | 930 | 87,396.0 | 0.0 | 93.97 | 0.9452 |
| `H3B_SL_3P0` | 930 | 100,129.0 | 12,733.0 | 107.67 | 0.9452 |
| `H4A_CAP_OFF` | 930 | 134,710.5 | 47,314.5 | 144.85 | 0.9452 |

### Old-Regime Slice `2020-2024`
Mini exclusion does not change this slice materially because the active mini roots were not carrying the old-period result.

| Profile | Filled trades | Net ticks (`2020-2024`) | Delta vs O1 |
| --- | ---: | ---: | ---: |
| `O1` | 730 | 77,426.5 | 0.0 |
| `H3B_SL_3P0` | 730 | 89,956.5 | 12,530.0 |
| `H4A_CAP_OFF` | 730 | 119,588.5 | 42,162.0 |

## Negative Months
The same four losing months remain after mini exclusion:
- `2021-02`
- `2021-08`
- `2022-02`
- `2025-02`

### `2021-02`
- Why negative:
  - one `PT (Platinum)` `PULLBACK_LIMIT BUY` on `2021-02-22` stopped out for `-166.5` net ticks in `O1`
  - `NG (Natural Gas)` trades that month were positive overall and only partly offset the platinum loss
- Interpretation:
  - this is not a broad strategy failure
  - it is a single-trade month dominated by one failed platinum pullback

### `2021-08`
- Why negative:
  - one `PD (Palladium)` `PULLBACK_LIMIT SELL` on `2021-08-23` exited at `-658.0` net ticks
  - `BR (Brent)`, `PT (Platinum)`, and `NG (Natural Gas)` were net positive in the same month
- Interpretation:
  - the month is again single-root dominated
  - the strategy was not broadly wrong across the universe; one palladium trade overwhelmed the smaller winners

### `2022-02`
- Why negative:
  - `MM (MXI)` contributed `-3723.0` in `O1`
  - `MX (MIX)` contributed `-887.0` in `O1`
  - the largest loss was `MM (MXI)` `PULLBACK_LIMIT SELL` on `2022-02-25`, `-5320.0`
  - the second-largest loss was `MX (MIX)` `PULLBACK_LIMIT SELL` on `2022-02-25`, `-1084.0`
  - `PD (Palladium)`, `NG (Natural Gas)`, and `BR (Brent)` were positive and partially offset the damage
- Interpretation:
  - this is the true stress month
  - the strategy lost on equity-index pullback shorts during a violent regime break on `2022-02-25`
  - `H4` helps here not by fixing the large losers, but by letting the positive roots keep more profit, which shrinks the month loss to `-1329.5`

### `2025-02`
- Why negative:
  - `MM (MXI)` `PULLBACK_LIMIT BUY` on `2025-02-26` lost `-1048.5` in `O1`
  - `RI (RTS Index)` added `-230.0`
  - `GD (Gold)` added `-53.0`
- Interpretation:
  - another concentrated month
  - the damage comes mostly from one failed MXI long pullback, not from broad weakness across many roots

## Thin-Sample Roots After Mini Exclusion

### Positive or Neutral but Thin
These roots are still too sparse for structural claims, even when profitable:
- `FF (TTF Gas)`: `2` trades, `1` month, `+67.5`
- `DJ (Dow Jones)`: `3` trades, `1` month, `+63.0`
- `SU (Sugar)`: `6` trades, `4` months, `+113.0`
- `N2 (Nikkei 225)`: `10` trades, `3` months, `+1233.0`
- `SF (S&P 500)`: `11` trades, `5` months, `+328.5`
- `CE (Copper)`: `15` trades, `4` months, `+279.0`
- `DX (DAX)`: `15` trades, `5` months, `+189.5`
- `SX (Euro Stoxx 50)`: `18` trades, `3` months, `+1796.0`

Interpretation:
- some are late-launch roots (`FF`, `CE`)
- some are episodic, not continuously active (`N2`, `SX`, `DJ`)
- they should stay in diagnostics, but not be treated as equal-confidence structural engines

### Negative Thin Roots
- `NC (Nickel)`: `2` trades, `1` month, `-10.0`
- `AN (Aluminum)`: `4` trades, `1` month, `-45.0`
- `KC (Coffee)`: `5` trades, `2` months, `-38.5`

Interpretation:
- these are too sparse to justify a hard exclusion purely from aggregate PnL
- but they are appropriate watchlist roots for future universe-pruning or late-launch audits

### `2025-2026` Thin-Root Slice
The late-period slice clarifies that "thin" is not one problem:

- `late-launch but active`:
  - `FF (TTF Gas)`: `2 planned / 2 filled`, `1` active month, `+67.5`
  - `CE (Copper)`: `15 planned / 15 filled`, `4` active months, `+351.0`
  - `NC (Nickel)`: `2 planned / 2 filled`, `1` active month, `-6.0`
  - `AN (Aluminum)`: `4 planned / 4 filled`, `1` active month, `-28.5`
  - `KC (Coffee)`: `5 planned / 5 filled`, `2` active months, `-13.0`
- `sparse-trigger but active`:
  - `DJ (Dow Jones)`: `3 planned / 3 filled`, `1` active month, `+129.0`
  - `SU (Sugar)`: `4 planned / 4 filled`, `2` active months, `+101.5`
- `current-regime silent`:
  - `N2 (Nikkei 225)`
  - `SF (S&P 500)`
  - `DX (DAX)`
  - `SX (Euro Stoxx 50)`

Interpretation:
- the active late-launch roots are not failing because of execution; `filled ~= planned` for all of them
- the active sparse roots are not data failures either; the strategy simply sees very few valid opportunities
- the `current-regime silent` group on `2025-2026` is entirely index-root driven, which is a family-level regime-fit observation rather than four unrelated instrument failures

### Monthly Histogram Artifact
- `H4A_CAP_OFF` no-mini monthly histogram:
  - `artifacts/research/h4_no_minis_monthly_revenue_histogram_20260306.svg`
  - `artifacts/research/h4_no_minis_monthly_revenue_histogram_20260306.png`

## Breadth After Mini Exclusion
- `H4A_CAP_OFF` still improves the whole universe strongly after removing duplicated exposure.
- Full-window delta `H4` vs `O1`: `+47,314.5` net ticks.
- `H4` still beats `O1` on the old-regime slice by `+42,162.0`.
- The uplift is still not only `PD (Palladium)`:
  - full `2020-2026` excluding `PD`: `O1=26083.0`, `H4=40190.5`

## Recommendation
- Accept the mini-exclusion rule as default universe hygiene.
- Promote `H4A_CAP_OFF` as the working execution baseline.
- Keep thin-sample roots in reports, but treat them as low-confidence evidence until they accumulate broader month coverage.
