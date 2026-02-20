# 0001 Dependency Decision Governance

## Status
Accepted

## Date
2026-02-20

## Context
Dependency and abstraction choices directly affect agent legibility, review safety, and maintenance cost.
Without a durable record, repeated fixes can drift into prompt-only responses instead of capability updates.

## Decision
Adopt ADR-first governance for dependency and abstraction decisions with a mechanical gate:
- maintain ADR records in `docs/architecture/adr/`,
- require ADR update when dependency manifests change,
- validate with `python scripts/validate_dependency_decisions.py` in CI and local lean loops.

## Consequences
- Pros:
  - dependency intent is versioned in-repo;
  - reviewers get explicit rationale and alternatives;
  - agents can infer expected boundaries from durable docs.
- Cons:
  - additional authoring overhead on dependency and abstraction changes.

## Alternatives Considered
1. Keep rationale only in PR description.
  - Rejected: weak long-term discoverability.
2. Keep rationale only in chat/planning tools.
  - Rejected: not versioned with code.
3. Rely on implicit conventions.
  - Rejected: non-deterministic and hard to enforce.

## Validation and Rollout
- Gate command:
  - `python scripts/validate_dependency_decisions.py`
- Process references:
  - `docs/DEV_WORKFLOW.md`
  - `docs/runbooks/governance-remediation.md`
