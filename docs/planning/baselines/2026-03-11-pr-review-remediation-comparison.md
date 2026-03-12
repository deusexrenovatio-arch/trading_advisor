# PR Review Remediation Timing Comparison

- Generated UTC: 2026-03-11T13:18:22+00:00
- Before source: `.runlogs/baselines/pr-review-remediation-before.json`
- After source: `.runlogs/baselines/pr-review-remediation-after.json`
- Iterations: 3 (cold + warm, p95 included).

| Profile | Before median (s) | After median (s) | Delta % | Before p95 (s) | After p95 (s) | Delta % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `session_check` | 0.118 | 0.127 | +7.6% | 0.123 | 0.128 | +4.1% |
| `surface_docs` | 1.977 | 0.339 | -82.9% | 2.257 | 0.343 | -84.8% |
| `surface_contracts` | 6.791 | 0.928 | -86.3% | 6.987 | 0.941 | -86.5% |
| `surface_core` | 10.700 | 0.678 | -93.7% | 10.818 | 0.689 | -93.6% |
| `surface_ui` | 2.124 | 0.511 | -75.9% | 2.135 | 0.520 | -75.6% |
| `loop` | 2.822 | 1.315 | -53.4% | 3.044 | 1.319 | -56.7% |

## Notes

- `surface_docs` now skips task-contract checks in docs-only loop runs.
- `surface_core` and `surface_contracts` use lightweight backend parity checks in loop fast path.
- `loop` excludes global default governance checks and only runs task-contract validation for non-trivial non-docs diffs.
