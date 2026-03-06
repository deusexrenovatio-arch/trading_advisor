# O1-Relative Execution Hypothesis Program (2026-03-06)

## Objective
- Quality in this research stream means larger net revenue after costs, not a prettier win rate by itself.
- Primary metric: `net_ticks_sum` relative to `O1`.
- Supporting diagnostics: `win_rate_net`, `trades_per_week`, concentration, fold dispersion, and stress stability.
- Promotion rule: no candidate replaces `O1` unless it beats `O1` on the same window and still respects hard constraints.

## O1 Reference Baseline
- Reference artifact: `artifacts/research/wf_goal_v6_h24_causal_rerun_execution_fixed_O1_limitfallback10m1t_frontnearest_seed124_20260305.json`
- Comparison artifact: `artifacts/research/wf_goal_v6_h24_execution_profile_compare_O4_vs_M3_seed124_20260306.json`
- Policy reference: `docs/research/evaluation-policy.md`
- Default assumption for every new hypothesis:
  - same universe
  - same date window
  - same decision times
  - same cost model
  - same news gate behavior
  - same seed and causal walk-forward structure

## Fixed Conclusions

### Primary optimization levers
- Fill quality:
  - `limit_entry_improve_ticks`
  - `limit_fallback_to_market_minutes`
  - `limit_fallback_slip_ticks`
- Trade management:
  - `break_even_rr`
  - `break_even_buffer_ticks`
  - `trail_activation_rr`
  - `trail_offset_ticks`
  - `max_holding_minutes`
- Bracket geometry, but only after the first two families are understood:
  - `tp_rr`
  - `sl_rr`

### Secondary guarded levers
- Target-clipping controls:
  - `max_profit_rr`
  - `max_profit_ticks`
- These are allowed only after the impact of fill quality and trade-management levers is already understood.
- Treat them as winner-clipping controls, not as the first path to improvement.

### Do-not-optimize levers
- `tp_cost_mult`
- `sl_cost_mult`
- `exit_cost_mult`
- These are cost-model assumptions, not economic alpha.
- `same_bar_policy`
- Use it only for sensitivity or stress checks, not as a primary optimization axis.

## Sequential Hypothesis Ladder

### H0: Reproduce O1 exactly
- Goal: confirm the active code path still reproduces the accepted O1 baseline on the frozen window.
- Output:
  - one artifact
  - parity delta versus O1 reference
  - explicit note if any drift appears

### H1: Fill-quality family
- H1a: vary `limit_entry_improve_ticks`
- H1b: vary `limit_fallback_to_market_minutes`
- H1c: vary `limit_fallback_slip_ticks`
- Rule:
  - keep all non-fill parameters at O1 values
  - test one lever first, then one tightly coupled pair only if single-axis direction is clear

### H2: Trade-management family
- H2a: vary `break_even_rr` and `break_even_buffer_ticks`
- H2b: vary `trail_activation_rr` and `trail_offset_ticks`
- H2c: vary `max_holding_minutes`
- Rule:
  - do not mix with H1 changes until H1 verdict is written

### H3: Bracket-geometry family
- H3a: vary `tp_rr`
- H3b: vary `sl_rr`
- H3c: test joint `tp_rr/sl_rr` only after the separate effects are understood
- Rule:
  - run this family only after H1 and H2 are classified

### H4: Target-clipping family
- H4a: vary `max_profit_rr`
- H4b: vary `max_profit_ticks`
- Rule:
  - use only if there is a concrete mechanism hypothesis about overextended winners or tail clipping

### H5: Sensitivity and stress only
- same-bar execution ordering
- harsher cost assumptions
- Rule:
  - these runs are for robustness only
  - they cannot be used as the main justification for baseline promotion

## Experiment Contract
- One hypothesis must make one causal claim.
- One family at a time.
- Every artifact must include:
  - hypothesis id
  - changed parameters
  - unchanged O1 parameters
  - delta versus O1
  - short mechanism note
  - verdict: `useful`, `noisy`, or `disallowed`
- If an improvement appears only because of looser simulator assumptions or friendlier cost modeling, mark it `disallowed`.

## Promotion Decision
- `pass`:
  - OOS gain versus O1
  - hard constraints respected
  - mechanism is economically credible
  - stress remains acceptable
- `hold`:
  - partial improvement or unclear mechanism
  - needs extra robustness evidence
- `fail`:
  - no gain versus O1
  - constraint breach
  - unstable fold behavior
  - pseudo-improvement caused by simulation assumptions

## Next Research Order
1. Reproduce `O1` on the current code path.
2. Run H1 fill-quality family.
3. Write a verdict before moving to H2.
4. Continue family-by-family until each lever is classified.

## Completed Run (2026-03-06)
- Final ladder summary: `artifacts/research/wf_goal_v6_h24_o1_execution_hypothesis_ladder_20260306.json`
- Full write-up: `docs/research/o1-execution-hypothesis-results-2026-03-06.md`
- Outcome:
  - `H0`: reproduced `O1` exactly.
  - `H1`: noisy.
  - `H2`: noisy.
  - `H3`: noisy but identified `sl_rr` as a real revenue lever with concentration cost.
  - `H4`: noisy but identified `max_profit_rr` clipping as the dominant revenue/concentration trade-off.
  - `H5`: disallowed for promotion; sensitivity only.
- Baseline decision after completed ladder: keep `O1`.
