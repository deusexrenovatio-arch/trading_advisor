# Agent Context Map

## Purpose
Keep AI-agent context small and deterministic by routing work to a bounded ownership slice.

## Context Catalog
- `CTX-DATA` -> `docs/agent-contexts/CTX-DATA.md`
- `CTX-STRATEGY` -> `docs/agent-contexts/CTX-STRATEGY.md`
- `CTX-RESEARCH` -> `docs/agent-contexts/CTX-RESEARCH.md`
- `CTX-NEWS` -> `docs/agent-contexts/CTX-NEWS.md`
- `CTX-ORCHESTRATION` -> `docs/agent-contexts/CTX-ORCHESTRATION.md`
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

Start-of-work behavior:
- `powershell -ExecutionPolicy Bypass -File scripts/worktree_guard.ps1 -Action Check` auto-runs `context_router`.
- Default routing input: changed files + `docs/session_handoff.md`.
- Optional intent sharpeners:
  - `MOEX_CARRY_CONTEXT_ROUTER_REQUEST="<user request>"`
  - `MOEX_CARRY_CONTEXT_ROUTER_TARGET_MODULES="pipeline,ui,news_live_runtime"`

Coverage validation:

```bash
python scripts/validate_agent_contexts.py
```

## Execution Rules
- Keep patch scope inside one context when possible.
- If no diff exists yet, use request/session fallback output and set an explicit target module for sharper routing.
- If one file pulls dependency hints from many CTX groups, treat it as orchestration work even if the file set is small.
- If a patch touches `CTX-CONTRACTS` plus another context, treat as high-risk and split into reviewable steps.
- If routing reports `unmapped_files`, classify manually before implementation.
- Treat `src/moex_carry/signal_engine/` as `CTX-STRATEGY` unless the change is purely runtime wiring in `config*`, `pipeline*`, or CLI entrypoints.

