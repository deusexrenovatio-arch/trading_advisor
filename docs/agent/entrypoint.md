# Agent Entrypoint (Hot Context)

This is the hot-path map for implementation turns. Keep it compact and route details to linked docs.

## Scope
- Goal: preserve strictness while minimizing mandatory context in the local loop.
- Hot docs are limited to this folder and must stay concise.

## Hot Docs
- `docs/agent/entrypoint.md` (this file)
- `docs/agent/domains.md`
- `docs/agent/checks.md`
- `docs/agent/runtime.md`
- `docs/agent/skills-routing.md`

## Retrieval Defaults
- Hot context: routing, ownership, current checks, runtime commands.
- Warm context: `docs/workflows/*`, runbooks, architecture deep dives.
- Cold context: plans, memory, archives, historical artifacts, full skill catalog.

## Non-Negotiable Loop
1. `python scripts/task_session.py begin --request "<request>"`
2. Update `docs/session_handoff.md` task contract.
3. Validate contract: `python scripts/validate_task_request_contract.py`
4. Run governance gate in the hot loop: `python scripts/run_loop_gate.py --from-git --git-ref HEAD`
5. Update `plans/PLANS.yaml` and `memory/agent_memory.yaml` only when durable decisions change; avoid pulling them into the hot loop by default.
6. Before push/PR run `python scripts/run_pr_gate.py --from-git --git-ref HEAD`, then close with `python scripts/task_session.py end`.

## PR-Only Policy
- PR-only flow for `main`: feature branch -> PR -> merge.
- Emergency override variables:
  - `MOEX_CARRY_EMERGENCY_MAIN_PUSH=1`
  - `MOEX_CARRY_EMERGENCY_MAIN_PUSH_REASON='<ticket/incident>'`

## Cold Context Escalation
- Open warm/cold docs only if hot docs are insufficient for deterministic implementation.
- If repeated failure appears, stop same-path patching and execute reset action from `## Repetition Control`.
