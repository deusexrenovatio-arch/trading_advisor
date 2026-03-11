# Dev Loop Timing Baseline

- Generated UTC: 2026-03-11T13:04:52+00:00
- Iterations per profile: 3
- Config: `configs/dev_loop_timing_profiles.yaml`

## Profile: `session_check`

Pure session-lock status check on the hot path.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `session_check` | 0.118 | 0.120 | 0.117 | 0.124 | 0.123 |
| `session_check: cold/warm` | 0.124 | 0.118 | 0.117 | 0.118 | 0.118 |
| `profile_total` | 0.118 | 0.120 | 0.117 | 0.124 | 0.123 |
| `profile_total: cold/warm` | 0.124 | 0.118 | 0.117 | 0.118 | 0.118 |

## Profile: `surface_docs`

Docs-only loop surface baseline with cold first run and warm follow-ups.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_docs_surface` | 1.977 | 2.044 | 1.866 | 2.288 | 2.257 |
| `loop_docs_surface: cold/warm` | 1.866 | 2.133 | 1.977 | 2.288 | 2.273 |
| `profile_total` | 1.977 | 2.044 | 1.866 | 2.288 | 2.257 |
| `profile_total: cold/warm` | 1.866 | 2.133 | 1.977 | 2.288 | 2.273 |

## Profile: `surface_contracts`

Contracts loop surface baseline with cold first run and warm follow-ups.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_contracts_surface` | 6.791 | 6.856 | 6.767 | 7.009 | 6.987 |
| `loop_contracts_surface: cold/warm` | 7.009 | 6.779 | 6.767 | 6.791 | 6.790 |
| `profile_total` | 6.791 | 6.856 | 6.767 | 7.009 | 6.987 |
| `profile_total: cold/warm` | 7.009 | 6.779 | 6.767 | 6.791 | 6.790 |

## Profile: `surface_core`

Core loop surface baseline with cold first run and warm follow-ups.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_core_surface` | 10.700 | 10.741 | 10.692 | 10.831 | 10.818 |
| `loop_core_surface: cold/warm` | 10.831 | 10.696 | 10.692 | 10.700 | 10.699 |
| `profile_total` | 10.700 | 10.741 | 10.692 | 10.831 | 10.818 |
| `profile_total: cold/warm` | 10.831 | 10.696 | 10.692 | 10.700 | 10.699 |

## Profile: `surface_ui`

UI loop surface baseline with cold first run and warm follow-ups.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_ui_surface` | 2.124 | 2.035 | 1.845 | 2.136 | 2.135 |
| `loop_ui_surface: cold/warm` | 1.845 | 2.130 | 2.124 | 2.136 | 2.136 |
| `profile_total` | 2.124 | 2.035 | 1.845 | 2.136 | 2.135 |
| `profile_total: cold/warm` | 1.845 | 2.130 | 2.124 | 2.136 | 2.136 |

## Profile: `loop`

Local hot-loop timing for day-to-day coding.

| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `loop_gate` | 2.822 | 2.873 | 2.729 | 3.068 | 3.044 |
| `loop_gate: cold/warm` | 3.068 | 2.776 | 2.729 | 2.822 | 2.818 |
| `profile_total` | 2.822 | 2.873 | 2.729 | 3.068 | 3.044 |
| `profile_total: cold/warm` | 3.068 | 2.776 | 2.729 | 2.822 | 2.818 |

