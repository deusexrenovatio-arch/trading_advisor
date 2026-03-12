# Dev Loop Timing Baseline

- Generated UTC: 2026-03-10T17:29:44+00:00
- Iterations per profile: 1
- Config: `configs/dev_loop_timing_profiles.yaml`

## Profile: `loop`

Local hot-loop timing for day-to-day coding.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) |
| --- | ---: | ---: | ---: | ---: |
| `lean_gate` | 6.513 | 6.513 | 6.513 | 6.513 |
| `worktree_guard` | 0.782 | 0.782 | 0.782 | 0.782 |
| `profile_total` | 7.295 | 7.295 | 7.295 | 7.295 |

## Profile: `pre_push`

Pre-push deterministic baseline for local quality gate.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) |
| --- | ---: | ---: | ---: | ---: |
| `architecture_smoke` | 3.339 | 3.339 | 3.339 | 3.339 |
| `frontend_contract` | 0.060 | 0.060 | 0.060 | 0.060 |
| `quality_scorecards` | 25.549 | 25.549 | 25.549 | 25.549 |
| `profile_total` | 28.948 | 28.948 | 28.948 | 28.948 |

## Profile: `ci`

CI-required jobs median baseline.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) |
| --- | ---: | ---: | ---: | ---: |
| `backend_smoke` | 3.312 | 3.312 | 3.312 | 3.312 |
| `frontend_contract` | 0.057 | 0.057 | 0.057 | 0.057 |
| `governance_contract` | 0.047 | 0.047 | 0.047 | 0.047 |
| `profile_total` | 3.416 | 3.416 | 3.416 | 3.416 |

