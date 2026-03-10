# ADR 0004: Codex-First Harness `loop -> pr -> nightly`

## Status
Accepted

## Date
2026-03-10

## Context
The repository currently enforces strong governance, but most checks are concentrated in a single all-in-one hot-path gate (`run_lean_gate`). This keeps strictness high, yet overloads local coding loops with global checks and broad-context retrieval pressure.

The redesign program requires:
- Keeping architecture, contract, runtime, and data-integrity strictness unchanged.
- Moving expensive/global checks to the right stage (`pr` and `nightly`) instead of running everything in `loop`.
- Shrinking mandatory hot context to routing information and scoped decision points.
- Preserving compatibility during migration with wrappers/shims and deterministic rollback paths.

## Decision
We adopt a three-level harness model:
- `loop`: smallest deterministic local gate for changed surface only.
- `pr`: widened, merge-relevant verification for touched domains.
- `nightly`: full cold-context and heavy governance hygiene.

Implementation policy:
1. Strictness moves between harness levels, never weakens.
2. Every migration step uses compatibility shims for one transition cycle.
3. Legacy entrypoints remain callable until nightly confirms new path stability.
4. Hot-context docs must stay compact and routing-oriented.
5. State migration (plans/memory/task notes) uses dual-write during transition.

Baseline policy:
- `scripts/harness_baseline_metrics.py` remains a structural invariants report only.
- Timing baselines are measured separately via `scripts/measure_dev_loop.py`.
- Every baseline capture is stored as a dated artifact under `docs/planning/baselines/`.

## Consequences
Positive:
- Lower local feedback latency without sacrificing final strictness.
- Clear operational separation between fast loop checks and deep hygiene checks.
- Better deterministic behavior in CI through scope-aware routing.

Trade-offs:
- Short-term complexity increase due to wrapper and dual-write compatibility layers.
- Temporary duplication of paths until transition window closes.

Risk controls:
- Mandatory validator runs before/after meaningful patch sets.
- Config-driven surface mapping used by both local gates and CI.
- Explicit deprecation notices for replaced entrypoints.

## Alternatives Considered
1. Keep single all-in-one lean gate and optimize individual validators.
   - Rejected: does not reduce hot-path context pressure and keeps expensive checks in every loop.
2. Add a second governance layer without changing entrypoints.
   - Rejected: increases cognitive load and duplicates policy wiring.
3. Immediate hard cut to new harness without compatibility layer.
   - Rejected: high migration risk and poor rollback/reproducibility.

## Validation and Rollout
1. `PR-00`: timing baseline tooling + this ADR.
2. `PR-01..PR-03`: context and state decomposition with compatibility.
3. `PR-04..PR-07`: change-surface engine and gate/validator split.
4. `PR-08..PR-11`: CI matrix, dependency profiles, canonical interfaces, runtime harness.
5. `PR-12..PR-13`: file-size policy + module split + root cleanup/nightly hygiene.

Validation commands:
- `python scripts/measure_dev_loop.py --iterations 1 --profiles loop`
- `python scripts/validate_dependency_decisions.py`
- `python scripts/run_lean_gate.py`
