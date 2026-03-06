# Session Handoff
Updated: 2026-03-06 13:12 UTC

## Goal
- Close strict acceptance for the unified `news_root_cycle` runtime by adding formal multi-commodity attribution validation, tightening deterministic linker behavior where needed, and proving the remaining benchmark threshold in addition to the already-passing discovery walk-forward targets.

## Task Request Contract
- Objective: close the remaining strict-pass acceptance gap after the runtime unification rollout by proving false multi-commodity assignment rate `<= 10%` on a formal benchmark, while preserving the already-implemented discovery/verified production routing and discovery walk-forward targets.
- In Scope: define a structured multi-commodity benchmark fixture; add a deterministic benchmark validator/report; tighten linker rules if benchmark reveals generic cross-commodity leakage; add regression tests; update runbook/session/plans/memory with the acceptance evidence and benchmark command.
- Out of Scope: re-opening production routing design, retraining models, changing strategy decision logic, changing the known-event walk-forward methodology, or silently downgrading synthetic validation targets.
- Constraints: benchmark must reflect production-style linking semantics (configured commodity universe and discovery min-link threshold), generic geopolitical/weather/mining tokens must not count as standalone commodity links, and the work must preserve the current single production route via `news_root_cycle`.
- Done Evidence: (1) formal benchmark dataset and validator exist in-repo, (2) targeted linker tests cover previous false-link patterns, (3) measured false multi-commodity assignment rate is `<= 10%`, (4) discovery walk-forward and operational validation remain green after linker changes.
- Priority Rule: acceptance-closing benchmark and linker correctness first, then regression protection and documentation of the new quality gate.

## Current Delta
- Production unification is implemented and validated.
- Discovery walk-forward still passes after linker hardening.
- Metrics remain `window_pass_rate=1.0`, `avg_known_event_coverage=0.976`, `avg_exact_event_recall=0.748`, `avg_precision=0.612`.
- A formal multi-commodity benchmark now exists at `docs/research/news_multi_commodity_benchmark.csv`.
- The deterministic linker now rejects weak generic anchors as standalone secondary links.
- The benchmark passes at discovery settings with `false_multi_commodity_assignment_rate=0.0`, `assignment_precision=1.0`, `assignment_recall=1.0`.

## First-Time-Right Report
1. Confirmed coverage: the task covers runtime entrypoint unification, feed split, default wiring into gate and Telegram, legacy route cleanup, and operational documentation truth.
2. Missing or risky scenarios: the remaining risk is validation blind spot, not runtime wiring; a weak benchmark could hide cross-commodity leakage, while over-generic anchor rules can still promote wrong secondary commodities.
3. Resource/time risks and chosen controls: keep the change narrow (linker + benchmark + tests), measure against a manually curated fixture before and after edits, and rerun discovery/operational checks to guard against regression.
4. Highest-priority fixes or follow-ups: remove weak-anchor false positives first, then lock a formal benchmark and validator so the acceptance target stays machine-checkable.

## Repetition Control
- Max Same-Path Attempts: 2
- Stop Trigger: two consecutive linker/benchmark iterations still fail the false-assignment threshold or require benchmark cases that no longer reflect production semantics.
- Reset Action: freeze the benchmark rows and inspect the exact false-link evidence row by row before making any further heuristic changes.
- New Search Space: (1) strong-vs-weak anchor separation, (2) graph-route evidence as a first-class link signal, (3) benchmark semantics aligned to discovery feed threshold and allowed commodity universe.
- Next Probe: run a formal curated benchmark against the current linker, then patch only the concrete false-link patterns exposed there.

## Blockers
- No blockers.

## Next Step
- Rerun final lean gate after plan/memory sync and keep the benchmark plus walk-forward artifacts as the strict-pass evidence bundle.

## Validation
- `python scripts/validate_task_request_contract.py`
- `python scripts/validate_session_handoff.py`
- `python scripts/run_lean_gate.py`
- `python scripts/news_multi_commodity_benchmark.py --benchmark-csv docs/research/news_multi_commodity_benchmark.csv --output-dir data/output/fullpass_multi_commodity_benchmark_20260306`
- `python scripts/news_known_events_walkforward.py --known-events-csv docs/research/news_golden_events_gold.csv --output-dir data/output/fullpass_known_events_discovery_20260306_linkbench --causal-profile discovery --warmup-days 120 --test-window-days 14 --step-days 14 --min-calibration-rows 60 --min-test-known-rows 6 --grid-min-fundamental 0.2,0.3,0.4,0.5,0.6 --grid-min-confidence 0.2,0.3,0.4,0.5,0.6 --min-calibration-precision 0.40 --gate-known-row-recall 0.90 --gate-known-event-coverage 0.90 --gate-precision 0.40`
- `pytest tests/test_news_linking.py tests/test_news_live_runtime.py tests/test_news_live_feed.py tests/test_telegram_news_broadcast.py tests/test_telegram_worker.py tests/test_news_shock_live_input.py tests/test_news_operational_contract.py -q`
