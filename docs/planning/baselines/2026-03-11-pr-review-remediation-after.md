# Dev Loop Timing Baseline

- Generated UTC: 2026-03-11T13:18:02+00:00
- Iterations per profile: 3
- Config: `configs/dev_loop_timing_profiles.yaml`

## Profile: `session_check`

Pure session-lock status check on the hot path.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_check` | 0.127 | 0.127 | 0.126 | 0.128 | 0.128 |
| `session_check: cold/warm` | 0.127 | 0.127 | 0.126 | 0.128 | 0.128 |
| `profile_total` | 0.127 | 0.127 | 0.126 | 0.128 | 0.128 |
| `profile_total: cold/warm` | 0.127 | 0.127 | 0.126 | 0.128 | 0.128 |

## Profile: `surface_docs`

Docs-only loop surface baseline with cold first run and warm follow-ups.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_docs_surface` | 0.339 | 0.339 | 0.333 | 0.344 | 0.343 |
| `loop_docs_surface: cold/warm` | 0.344 | 0.336 | 0.333 | 0.339 | 0.338 |
| `profile_total` | 0.339 | 0.339 | 0.333 | 0.344 | 0.343 |
| `profile_total: cold/warm` | 0.344 | 0.336 | 0.333 | 0.339 | 0.338 |

## Profile: `surface_contracts`

Contracts loop surface baseline with cold first run and warm follow-ups.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_contracts_surface` | 0.928 | 0.927 | 0.910 | 0.942 | 0.941 |
| `loop_contracts_surface: cold/warm` | 0.942 | 0.919 | 0.910 | 0.928 | 0.927 |
| `profile_total` | 0.928 | 0.927 | 0.910 | 0.942 | 0.941 |
| `profile_total: cold/warm` | 0.942 | 0.919 | 0.910 | 0.928 | 0.927 |

## Profile: `surface_core`

Core loop surface baseline with cold first run and warm follow-ups.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_core_surface` | 0.678 | 0.675 | 0.656 | 0.691 | 0.689 |
| `loop_core_surface: cold/warm` | 0.678 | 0.673 | 0.656 | 0.691 | 0.689 |
| `profile_total` | 0.678 | 0.675 | 0.656 | 0.691 | 0.689 |
| `profile_total: cold/warm` | 0.678 | 0.673 | 0.656 | 0.691 | 0.689 |

## Profile: `surface_ui`

UI loop surface baseline with cold first run and warm follow-ups.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_ui_surface` | 0.511 | 0.508 | 0.490 | 0.521 | 0.520 |
| `loop_ui_surface: cold/warm` | 0.521 | 0.501 | 0.490 | 0.511 | 0.510 |
| `profile_total` | 0.511 | 0.508 | 0.490 | 0.521 | 0.520 |
| `profile_total: cold/warm` | 0.521 | 0.501 | 0.490 | 0.511 | 0.510 |

## Profile: `loop`

Local hot-loop timing for day-to-day coding.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_gate` | 1.315 | 1.311 | 1.299 | 1.319 | 1.319 |
| `loop_gate: cold/warm` | 1.315 | 1.309 | 1.299 | 1.319 | 1.318 |
| `profile_total` | 1.315 | 1.311 | 1.299 | 1.319 | 1.319 |
| `profile_total: cold/warm` | 1.315 | 1.309 | 1.299 | 1.319 | 1.318 |

