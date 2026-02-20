# Context Budget Workflow

## Purpose
- Keep team context usage predictable in long sessions.
- Move durable state to repository artifacts instead of chat transcripts.

## Mandatory Contract
1. Keep chat updates delta-first:
   - progress updates: 1-2 sentences,
   - final summary: compact change/result block.
2. Do not paste large instruction blocks or skill catalogs into status updates.
3. Use repository state for continuity:
   - `plans/PLANS.yaml` for execution status,
   - `memory/agent_memory.yaml` for durable decisions/incidents/patterns,
   - `docs/session_handoff.md` for short task delta.
4. Keep `docs/session_handoff.md` lean:
   - `## Current Delta` maximum 8 bullets,
   - no high-context instruction dumps.

## Mechanical Gate
- Validation command:
  - `python scripts/validate_session_handoff.py`
- The command is part of:
  - `python scripts/run_lean_gate.py`

## Failure Remediation
- Follow `docs/runbooks/governance-remediation.md`.
- Reduce handoff content to the smallest actionable delta and rerun the gate.
