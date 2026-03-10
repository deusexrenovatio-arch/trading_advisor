# Agent Domains Map

Use this map to select the minimal context for a patch.

| Context | Owns | Key boundaries |
| --- | --- | --- |
| `CTX-DATA` | ingestion, minute data, history | avoid UI/runtime coupling |
| `CTX-STRATEGY` | signal logic, risk, portfolio, selection | contracts and storage are guarded |
| `CTX-RESEARCH` | backtest/replay/HPO/perf | keep runtime and UI boundaries clean |
| `CTX-NEWS` | news ingestion, scoring, shock pipeline | no hidden coupling to storage/UI |
| `CTX-ORCHESTRATION` | CLI/config/runtime wiring | keep adapters thin across contexts |
| `CTX-API-UI` | API delivery, UI behavior, integrations | avoid importing strategy internals |
| `CTX-CONTRACTS` | schemas, storage contracts, decision logs | high-risk context, patch in ordered series |
| `CTX-OPS` | governance scripts, checks, process tooling | do not drag cold context into hot loop |

## Routing Rule
- Prefer one primary context per patch.
- If multiple contexts are touched, split change series in order:
  1. contracts
  2. code
  3. docs

## Cold Context Defaults
- Treat `plans/`, `memory/`, `artifacts/`, archives, and skill catalog as cold.
- Pull these files only when explicitly required by the current acceptance path.
