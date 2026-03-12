# Dev Loop Timing Baseline

- Generated UTC: 2026-03-11T07:23:24+00:00
- Iterations per profile: 3
- Config: `configs/dev_loop_timing_profiles.yaml`

## Profile: `session_check`

Pure session-lock status check on the hot path.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_check` | 0.107 | 0.108 | 0.105 | 0.112 | 0.112 |
| `session_check: cold/warm` | 0.112 | 0.106 | 0.105 | 0.107 | 0.107 |
| `profile_total` | 0.107 | 0.108 | 0.105 | 0.112 | 0.112 |
| `profile_total: cold/warm` | 0.112 | 0.106 | 0.105 | 0.107 | 0.107 |

## Profile: `surface_docs`

Docs-only loop surface baseline with cold first run and warm follow-ups.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_docs_surface` | 1.887 | 1.891 | 1.792 | 1.994 | 1.983 |
| `loop_docs_surface: cold/warm` | 1.792 | 1.940 | 1.887 | 1.994 | 1.988 |
| `profile_total` | 1.887 | 1.891 | 1.792 | 1.994 | 1.983 |
| `profile_total: cold/warm` | 1.792 | 1.940 | 1.887 | 1.994 | 1.988 |

## Profile: `surface_contracts`

Contracts loop surface baseline with cold first run and warm follow-ups.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_contracts_surface` | 6.404 | 6.477 | 6.368 | 6.659 | 6.634 |
| `loop_contracts_surface: cold/warm` | 6.659 | 6.386 | 6.368 | 6.404 | 6.402 |
| `profile_total` | 6.404 | 6.477 | 6.368 | 6.659 | 6.634 |
| `profile_total: cold/warm` | 6.659 | 6.386 | 6.368 | 6.404 | 6.402 |

## Profile: `surface_core`

Core loop surface baseline with cold first run and warm follow-ups.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_core_surface` | 10.163 | 10.209 | 10.076 | 10.390 | 10.367 |
| `loop_core_surface: cold/warm` | 10.076 | 10.276 | 10.163 | 10.390 | 10.379 |
| `profile_total` | 10.163 | 10.209 | 10.076 | 10.390 | 10.367 |
| `profile_total: cold/warm` | 10.076 | 10.276 | 10.163 | 10.390 | 10.379 |

## Profile: `surface_ui`

UI loop surface baseline with cold first run and warm follow-ups.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_ui_surface` | 1.910 | 1.871 | 1.758 | 1.947 | 1.943 |
| `loop_ui_surface: cold/warm` | 1.758 | 1.928 | 1.910 | 1.947 | 1.945 |
| `profile_total` | 1.910 | 1.871 | 1.758 | 1.947 | 1.943 |
| `profile_total: cold/warm` | 1.758 | 1.928 | 1.910 | 1.947 | 1.945 |

## Profile: `loop`

Local hot-loop timing for day-to-day coding.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_gate` | 11.075 | 11.093 | 10.972 | 11.233 | 11.217 |
| `loop_gate: cold/warm` | 11.233 | 11.024 | 10.972 | 11.075 | 11.070 |
| `profile_total` | 11.075 | 11.093 | 10.972 | 11.233 | 11.217 |
| `profile_total: cold/warm` | 11.233 | 11.024 | 10.972 | 11.075 | 11.070 |

## Profile: `pre_push`

Pre-push deterministic baseline for local quality gate.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `architecture_smoke` | 3.862 | 3.842 | 3.795 | 3.869 | 3.869 |
| `architecture_smoke: cold/warm` | 3.869 | 3.829 | 3.795 | 3.862 | 3.859 |
| `frontend_contract` | 0.056 | 0.057 | 0.055 | 0.060 | 0.059 |
| `frontend_contract: cold/warm` | 0.055 | 0.058 | 0.056 | 0.060 | 0.060 |
| `quality_scorecards` | 21.166 | 21.237 | 21.142 | 21.403 | 21.379 |
| `quality_scorecards: cold/warm` | 21.142 | 21.284 | 21.166 | 21.403 | 21.391 |
| `profile_total` | 25.066 | 25.136 | 25.020 | 25.321 | 25.296 |
| `profile_total: cold/warm` | 25.066 | 25.171 | 25.020 | 25.321 | 25.306 |

## Profile: `ci`

CI-required jobs median baseline.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `backend_smoke` | 3.729 | 3.750 | 3.660 | 3.862 | 3.849 |
| `backend_smoke: cold/warm` | 3.862 | 3.695 | 3.660 | 3.729 | 3.726 |
| `frontend_contract` | 0.054 | 0.054 | 0.052 | 0.056 | 0.056 |
| `frontend_contract: cold/warm` | 0.052 | 0.055 | 0.054 | 0.056 | 0.056 |
| `governance_contract` | 0.048 | 0.047 | 0.045 | 0.048 | 0.048 |
| `governance_contract: cold/warm` | 0.048 | 0.046 | 0.045 | 0.048 | 0.048 |
| `profile_total` | 3.831 | 3.851 | 3.762 | 3.962 | 3.949 |
| `profile_total: cold/warm` | 3.962 | 3.796 | 3.762 | 3.831 | 3.827 |

