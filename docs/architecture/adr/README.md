# ADR Index

Architecture Decision Records (ADR) capture dependency and abstraction decisions that affect agent legibility.

## Naming
- File pattern: `docs/architecture/adr/NNNN-short-kebab-title.md`
- `NNNN` is a 4-digit sequence (for example: `0001`).

## Required Sections
- `Status`
- `Date`
- `Context`
- `Decision`
- `Consequences`
- `Alternatives Considered`
- `Validation and Rollout`

## Trigger Policy
Create or update an ADR when changing:
- `pyproject.toml`
- `ui-web/package.json`
- `ui-web/package-lock.json`
- high-impact architectural abstractions in `src/` or `ui-web/src/`

## Validation
- `python scripts/validate_dependency_decisions.py`

## Template
Use the structure from `docs/architecture/adr/0001-dependency-decision-governance.md`.
