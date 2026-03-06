# O1-Relative Execution Hypothesis Results (2026-03-06)

## Experiment scope
- Hypothesis: complete the `H0`-`H5` execution ladder relative to frozen `O1` and keep only candidates that improve `net_ticks_sum` without violating the same hard constraints.
- Data window: `2025-03-01` to `2026-03-02`
- Execution mode: causal walk-forward on front-nearest commodity futures, `10:30 / 12:00 / 14:15` MSK
- Objective + constraints: maximize `net_ticks_sum` relative to `O1`, but do not promote any candidate that still fails the same hard-go concentration gate.

## Reference baseline
- Reference artifact: `artifacts/research/wf_goal_v6_h24_causal_rerun_execution_fixed_O1_limitfallback10m1t_frontnearest_seed124_20260305.json`
- Ladder summary artifact: `artifacts/research/wf_goal_v6_h24_o1_execution_hypothesis_ladder_20260306.json`
- `O1` metrics:
  - `filled_trades=222`
  - `win_rate_net=0.9414`
  - `trades_per_week=4.2343`
  - `net_ticks_sum=12605.5`
  - `concentration_top_share=0.5322`
  - `acceptance=false` because `hard_max_concentration_top_share`

## Family verdicts

### H0
- Verdict: `useful`
- Result: exact reproduction of frozen `O1`; no active-code-path drift detected.
- Artifact: `artifacts/research/wf_goal_v6_h24_o1_h0_repro_20260306.json`

### H1 Fill Quality
- Verdict: `noisy`
- Main findings:
  - `H1B_FALLBACK_0M` crushed net to `3743.0` (`-8862.5` vs `O1`), so LIMIT fallback is essential.
  - `H1A_IMPROVE_0` and `H1A_IMPROVE_2` moved net only by `+57.0` and `+40.0`.
  - `H1C_FALLBACK_SLIP_2` was the best variant at `+63.5`, but the effect is too small to justify baseline change.
- Conclusion: fill-quality around current `O1` is second-order; fallback existence matters, fine tuning does not.
- Artifact: `artifacts/research/wf_goal_v6_h24_o1_h1_family_summary_20260306.json`

### H2 Trade Management
- Verdict: `noisy`
- Main findings:
  - Break-even changes were inert on this window: `H2A_BE_OFF` and `H2A_BE_LATER` matched `O1`.
  - Trailing is a real positive contributor: `H2B_TRAIL_OFF` dropped net by `-2221.0`, although it did heal concentration enough to pass.
  - `H2C_HOLD_240` added only `+57.0`; `H2C_HOLD_120` lost `-20.0`.
- Conclusion: current trailing logic is economically useful, but the family does not produce a promotable improvement versus `O1`.
- Artifact: `artifacts/research/wf_goal_v6_h24_o1_h2_family_summary_20260306.json`

### H3 Bracket Geometry
- Verdict: `noisy`
- Main findings:
  - TP geometry is inert here: `H3A_TP_SETUP` and `H3A_TP_0P8` matched `O1`.
  - Stop geometry is strong: `H3B_SL_3P0` added `+680.0` net ticks.
  - The problem is concentration: `H3B_SL_3P0` raised `concentration_top_share` to `0.5813`, so promotion is blocked.
- Conclusion: stop widening is a real revenue lever, but not a valid baseline replacement under current constraints.
- Artifacts:
  - `artifacts/research/wf_goal_v6_h24_o1_h3_family_summary_20260306.json`
  - `artifacts/research/wf_goal_v6_h24_o1_h3b_sl_3p0_20260306.json`

### H4 Clipping Controls
- Verdict: `noisy`
- Main findings:
  - `H4A_CAP_OFF` was the strongest revenue variant in the whole ladder: `net_ticks_sum=17913.0`, delta `+5307.5`.
  - `H4A_CAP_0P4` still improved net by `+2365.0`.
  - Absolute caps fixed concentration enough to pass:
    - `H4B_ABS_CAP_120`: `concentration_top_share=0.2217`, `acceptance=true`
    - `H4B_ABS_CAP_240`: `concentration_top_share=0.3335`, `acceptance=true`
  - But those acceptance gains came with severe revenue loss:
    - `H4B_ABS_CAP_120`: `-5243.5` net ticks vs `O1`
    - `H4B_ABS_CAP_240`: `-3786.5` net ticks vs `O1`
- Conclusion: winner clipping is the dominant trade-off in this execution profile. Removing the RR cap lifts revenue sharply; hard clipping fixes concentration but destroys too much net.
- Artifacts:
  - `artifacts/research/wf_goal_v6_h24_o1_h4_family_summary_20260306.json`
  - `artifacts/research/wf_goal_v6_h24_o1_h4a_cap_off_20260306.json`

### H5 Sensitivity Only
- Verdict: `disallowed`
- Main findings:
  - `same_bar_policy=tp_first` added only `+25.5`.
  - `same_bar_policy=sl_first` lost `-142.0`.
  - Cost stress reduced net as expected:
    - `1.25x`: `-88.875`
    - `1.50x`: `-177.75`
- Conclusion: these runs are useful only as robustness checks; they cannot justify baseline promotion.
- Artifact: `artifacts/research/wf_goal_v6_h24_o1_h5_family_summary_20260306.json`

## Recommendation
- Keep `O1` as the primary execution baseline.
- Do not reopen `H1`, `H2`, or `H5` as primary tuning axes on this frozen window.
- The next search space should be explicitly concentration-aware and centered on the unresolved `H3/H4` trade-off:
  - stop geometry and winner clipping clearly move revenue,
  - but current variants either worsen concentration or over-fix it by sacrificing too much net.

## Promotion decision
- `pass`: none
- `hold`: `H3B_SL_3P0` and `H4A_CAP_OFF` as mechanism evidence only
- `fail`: all other `H1`-`H4` candidates for baseline promotion
- Baseline after completed ladder: `O1`
