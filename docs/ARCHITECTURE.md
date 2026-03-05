# Architecture Overview

This document is the canonical architecture entry point for the repository.

## Purpose
- Define the stable architecture navigation path for contributors and AI agents.
- Keep module boundaries and ownership discoverable from one file.
- Route architectural changes to required governance checks before merge.

## Core Architecture Artifacts
- [Architecture map v2](architecture/architecture-map-v2.md)
- [Layer model](architecture/layers-v2.md)
- [Entity model](architecture/entities-v2.md)
- [Trading advisor architecture](architecture/trading-advisor.md)
- [Module specs](architecture/modules/)
- [ADR index](architecture/adr/README.md)
- [Agent context map](agent-contexts/README.md)

## Boundary Rules
- Keep `ui` as composition root; domain behavior belongs to focused modules.
- Contract and registry changes must be documented before behavior changes.
- Cross-module dependencies must follow declared architecture policy and avoid shared-storage shortcuts.
- Any dependency or high-impact abstraction change requires an ADR update under `docs/architecture/adr/`.

## Governance Checks
- `python scripts/validate_architecture_policy.py`
- `python scripts/sync_architecture_map.py --check`
- `python scripts/run_lean_gate.py`

If a check fails, follow [governance remediation runbook](runbooks/governance-remediation.md).
