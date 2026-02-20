# Flaky Tests Policy

## Scope
Policy for flaky tests in backend, frontend, and e2e suites.

## Definitions
- Flaky test: same commit produces both pass and fail without deterministic input changes.

## Policy
1. Do not ignore flakes silently.
2. Quarantine only with explicit owner and expiry.
3. Keep retries bounded and documented.
4. Quarantined tests still require follow-up plan and SLA.

## Required Metadata
- Owner team or person.
- First seen date.
- Quarantine expiry date.
- Tracking issue link.
- Exit criteria.

## CI Behavior
- Retry budget is limited by `configs/flaky_policy.yaml`.
- Exceeding quarantine limits or SLA breaches is a blocker.

## Validation
- `python scripts/validate_flaky_policy.py`
