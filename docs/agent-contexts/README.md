# Agent Context Map

## Purpose
Keep AI-agent context small and deterministic by routing work to a bounded ownership slice.

## Context Catalog
- `CTX-DATA` -> `docs/agent-contexts/CTX-DATA.md`
- `CTX-STRATEGY` -> `docs/agent-contexts/CTX-STRATEGY.md`
- `CTX-RESEARCH` -> `docs/agent-contexts/CTX-RESEARCH.md`
- `CTX-API-UI` -> `docs/agent-contexts/CTX-API-UI.md`
- `CTX-CONTRACTS` -> `docs/agent-contexts/CTX-CONTRACTS.md`
- `CTX-OPS` -> `docs/agent-contexts/CTX-OPS.md`

## Task Start Block (mandatory)
For each task, start with three source-of-truth links:

```md
SOT:
- AGENTS.md
- docs/architecture/modules/<target-module>.md
- contracts/decision-log.schema.json or docs/contracts/api-v2.yaml
```

## Routing Script
Use `scripts/context_router.py` to assign context from changed files:

```bash
python scripts/context_router.py --from-git --format text
```

Or from explicit file list:

```bash
python scripts/context_router.py --changed-files src/moex_carry/ui/app.py docs/contracts/api-v2.yaml --format json --pretty
```

## Execution Rules
- Keep patch scope inside one context when possible.
- If a patch touches `CTX-CONTRACTS` plus another context, treat as high-risk and split into reviewable steps.
- If routing reports `unmapped_files`, classify manually before implementation.

