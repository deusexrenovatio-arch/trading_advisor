# CTX-ORCHESTRATION

## Scope
Entrypoints, runtime wiring, configuration, and cross-context orchestration.

## Owned Paths
- `src/moex_carry/__main__.py`
- `src/moex_carry/cli.py`
- `src/moex_carry/cli_news_handlers.py`
- `src/moex_carry/cli_news_parsers.py`
- `src/moex_carry/cli_news_runtime_handlers.py`
- `src/moex_carry/config.py`
- `src/moex_carry/config_resolver.py`
- `src/moex_carry/pipeline.py`
- `src/moex_carry/pipeline_helpers.py`
- `src/moex_carry/parameter_specs.py`
- `src/moex_carry/unified_runtime.py`

## Guarded Paths (do not change in this context)
- `src/moex_carry/storage/`
- `contracts/`
- `ui-web/`

## Input/Output Contracts
- Input: operator requests, config/settings, and module-level runtime adapters.
- Output: deterministic task wiring, entrypoint behavior, and cross-context orchestration paths.

## Invariants
- Keep orchestration thin: route across contexts, do not absorb domain logic.
- If dependency hints span many contexts, split adapter extraction from behavior changes.

## Minimum Checks
- `python scripts/run_lean_gate.py`
- `python scripts/validate_architecture_policy.py`
