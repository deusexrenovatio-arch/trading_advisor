# External Advice Mapping (2026-03-04)

## Scope
- Application context: intraday futures trading advisor with deterministic gates, risk-first policy, replay parity, and strict governance loop.
- Existing baseline already in place: worktree guard, lean gate, plans/memory/handoff, first-time-right, PR-only flow, quality scorecards, architecture policy, self-heal.
- Goal of this mapping: evaluate each concrete external advice for practical value in this repository and decide `ADOPT`, `ADAPT`, `DEFER`, or `REJECT`.

## Usefulness rubric
- `High`: directly reduces production risk, repeated failures, or governance drift in this repo.
- `Medium`: useful productivity gain, but lower direct impact on risk/quality invariants.
- `Low`: weak fit for current tooling/runtime or duplicates existing controls.

---

## Source A: Boris Way (`guides.gritai.studio`)

| ID | Advice (paraphrased) | Usefulness | Current state | Decision | Repository action |
| --- | --- | --- | --- | --- | --- |
| B01 | Use `explore -> plan -> code` | High | Covered | ADOPTED | `docs/DEV_WORKFLOW.md`, first-time-right, request contract |
| B02 | Build context from docs before coding | High | Covered | ADOPTED | source-of-truth contract in `AGENTS.md` |
| B03 | Ask for deeper reasoning on hard tasks | Medium | Partial | ADAPTED | explicit first-time-right risk block, not model-specific keyword |
| B04 | Use images for UI tasks | Medium | Partial | ADAPTED | frontend skill allows visual checks when relevant |
| B05 | Keep memory file (`CLAUDE.md`) updated | High | Covered | ADOPTED | `memory/agent_memory.yaml` + validator |
| B06 | Build features that can be tested quickly | High | Covered | ADOPTED | lean gate + required checks |
| B07 | Tell agent to read files first | High | Covered | ADOPTED | progressive disclosure rules in AGENTS/workflows |
| B08 | Narrow context to avoid drift | High | Covered | ADOPTED | context-budget gate + handoff validator |
| B09 | Add concrete examples to docs | Medium | Partial | ADAPTED | checklist/runbook examples where operationally critical |
| B10 | Prompt with role/goals/constraints | High | Covered | ADOPTED | task request contract gate |
| B11 | Prompt by outcomes, not implementation | High | Covered | ADOPTED | required objective + done-evidence fields |
| B12 | Ask for plan before coding | High | Covered | ADOPTED | first-time-right protocol + plan registry |
| B13 | Use direct tools, avoid copy-paste loops | Medium | Covered | ADOPTED | scripts/hooks/validators as first-class flow |
| B14 | Force step-by-step tasks + acceptance criteria | High | Covered | ADOPTED | first-time-right + request contract |
| B15 | For complex tasks: plan/evaluate before implementation | High | Covered | ADOPTED | first-time-right gate sequence |
| B16 | If fix is weak, provide command+error and retry | Medium | Covered | ADOPTED | remediation runbook and deterministic rerun |
| B17 | Update memory after each correction | High | Covered | ADOPTED | memory updates required in loop |
| B18 | Use context reset (`clear/compact`) aggressively | High | Partial | ADAPTED | repetition-control gate with forced reset action |
| B19 | Do not skip safety permissions | High | Partial | ADAPTED | PR-only + hooks + governance blockers (tooling differs from Claude CLI) |
| B20 | Use post-tool hooks for deterministic automation | High | Covered | ADOPTED | `.githooks`, pre-commit/pre-push validators |
| B21 | Parallel sessions with branch isolation | High | Covered | ADOPTED | `parallel-worktree-flow` skill |
| B22 | Start fresh session after spec finalization | High | Partial | ADAPTED | mandatory repetition reset + new search-space probe |

---

## Source B: Claude Code Best Practices (`code.claude.com`)

| ID | Advice (paraphrased) | Usefulness | Current state | Decision | Repository action |
| --- | --- | --- | --- | --- | --- |
| A01 | Give docs as markdown for verifiable claims | High | Covered | ADOPTED | source-of-truth and docs-first governance |
| A02 | Use explore/plan/code loop | High | Covered | ADOPTED | first-time-right + lean loop |
| A03 | Provide specific context/instructions | High | Covered | ADOPTED | task request contract |
| A04 | Provide rich context/examples/screenshots | Medium | Partial | ADAPTED | selectively required for UI/high-risk flows |
| A05 | Configure environment for agent efficiency | Medium | Covered | ADOPTED | worktree/ports/runbook policy |
| A06 | Maintain effective persistent memory file | High | Covered | ADOPTED | `memory/agent_memory.yaml` |
| A07 | Configure command permissions safely | High | Partial | ADAPTED | hooks + governance blockers (different runtime model) |
| A08 | Use CLI tools for repetitive tasks | High | Covered | ADOPTED | script-first policy in workflow |
| A09 | Use MCP servers for external systems | Low | Not used | DEFERRED | not required for current architecture |
| A10 | Set deterministic hooks | High | Covered | ADOPTED | pre-commit/pre-push + validators |
| A11 | Create reusable skills | High | Covered | ADOPTED | local skill catalog + validation |
| A12 | Create custom subagents | Medium | Partial | ADAPTED | parallel worktrees/streams instead of Claude subagents |
| A13 | Install plugins where beneficial | Low | Not used | DEFERRED | low ROI vs current Python/script stack |
| A14 | Communicate explicitly and structurally | High | Covered | ADOPTED | task contract + first-time-right report format |
| A15 | Ask codebase questions before editing | High | Covered | ADOPTED | progressive disclosure and pre-edit checks |
| A16 | Let agent interview operator when ambiguous | High | Partial | ADAPTED | hard rejection of vague/contradictory contracts |
| A17 | Manage sessions (`clear/compact/checkpoint`) | High | Partial | ADAPTED | repetition-control stop/reset/new-search |
| A18 | Use non-interactive mode for automation | Medium | Covered | ADOPTED | scheduled scripts + unattended tasks |
| A19 | Run multiple sessions in parallel | High | Covered | ADOPTED | worktree topology and merge order |
| A20 | Fan out independent tasks | High | Covered | ADOPTED | ownership contexts + split patch guidance |
| A21 | Use safe autonomous mode in isolated environment | High | Partial | ADAPTED | local runbook thresholds + guardrails; containerization is deferred |
| A22 | Resume previous session deterministically | Medium | Partial | ADAPTED | session handoff as canonical continuity artifact |
| A23 | Use context compaction aggressively | High | Covered | ADOPTED | context budget contract + validator |
| A24 | Track usage/cost budget | Medium | Partial | ADAPTED | quality/governance budgeting exists; model-cost budget not needed here |
| A25 | Use checkpoints and rewind instead of blind edits | High | Partial | ADAPTED | same-path attempt cap + reset protocol |
| A26 | Keep toolchain updated | Medium | Partial | DEFERRED | done per release/ADR, not as per-task blocker |

---

## Source C: Claude Code Tips (`github.com/ykdojo/claude-code-tips`)

| ID | Advice (paraphrased from tip title) | Usefulness | Current state | Decision | Repository action |
| --- | --- | --- | --- | --- | --- |
| C00 | Why to use Claude Code effectively | Medium | Covered | ADOPTED | baseline motivation already absorbed |
| C01 | Install and basic setup | Medium | Covered | ADOPTED | dev workflow bootstrap exists |
| C02 | Use/avoid list for commands | High | Partial | ADAPTED | governance rules + runbook dos/donts |
| C03 | Maximize context quality | High | Covered | ADOPTED | context budget + task contract |
| C04 | Encourage planning + self-check | High | Covered | ADOPTED | first-time-right + lean loop |
| C05 | Prime with task-management rules | High | Covered | ADOPTED | request contract + plans registry |
| C06 | Keep TODO list during execution | High | Covered | ADOPTED | `plans/PLANS.yaml` |
| C07 | Tune model/reasoning effort | Low | Not direct | DEFERRED | platform-level, not repo governance |
| C08 | Use custom slash commands | Low | Not direct | DEFERRED | tool-specific to Claude CLI |
| C09 | Use custom output styles | Low | Partial | DEFERRED | low risk impact for this repo |
| C10 | Hidden prompts/forbidden words | Low | Not used | REJECTED | weak engineering value for this stack |
| C11 | Generate terminal setup command | Low | Not direct | DEFERRED | environment already scripted |
| C12 | Ask for explanation before implementation | Medium | Covered | ADOPTED | review-first on ambiguous tasks |
| C13 | Create checkpoints and rewind | High | Partial | ADAPTED | repetition-control reset + capped attempts |
| C14 | Use git heavily | High | Covered | ADOPTED | branch/worktree/PR-only policy |
| C15 | Half-clone strategy | Low | Not needed | REJECTED | repo size/workflow does not require it |
| C16 | Configure permissions explicitly | High | Partial | ADAPTED | hooks/blockers instead of Claude permissions |
| C17 | Reuse prompts/instructions | Medium | Covered | ADOPTED | source-of-truth governance docs |
| C18 | Clear context with `/clear` | High | Partial | ADAPTED | reset action required in repetition control |
| C19 | Compact context with `/compact` | High | Covered | ADOPTED | handoff/context budget workflow |
| C20 | Pass images for visual tasks | Medium | Partial | ADAPTED | used when UI tasks require it |
| C21 | Use deep-think mode for hard tasks | Medium | Partial | ADAPTED | first-time-right depth instead of model token |
| C22 | Ask for parallel tool calls | High | Covered | ADOPTED | parallel reads/checks in workflow |
| C23 | Use multiple instances in parallel | High | Covered | ADOPTED | worktree parallel flow |
| C24 | Split routines into mini-agents | Medium | Partial | ADAPTED | stream split via contexts/skills |
| C25 | Use codebase Q&A/note mode | Medium | Covered | ADOPTED | progressive discovery and bounded reads |
| C26 | Ask AI for commit/PR text | Medium | Covered | ADOPTED | commit hygiene and PR artifacts |
| C27 | Ask AI to process PR comments | Medium | Partial | DEFERRED | currently manual; can add later |
| C28 | Ask AI to review docs drift | High | Covered | ADOPTED | docs-sync + gardening workflows |
| C29 | Script recurring tasks | High | Covered | ADOPTED | heavy script-first culture |
| C30 | Automate and improve scripts continuously | High | Covered | ADOPTED | self-heal/docs-gardening loops |
| C31 | Use hooks for auto-checks | High | Covered | ADOPTED | pre-commit/pre-push hooks |
| C32 | Add status-line script | Low | Not used | DEFERRED | limited incremental value |
| C33 | Audit approved commands (`cc-safe`) | High | Partial | ADAPTED | current command safety is enforced via hooks/governance blockers; dedicated command-audit tool deferred |
| C34 | Search command history quickly | Low | Partial | DEFERRED | optional local productivity |
| C35 | Chat from terminal output | Medium | Covered | ADOPTED | command-output-driven remediation flow |
| C36 | Execute specific command directly | High | Covered | ADOPTED | “show command + rerun” loop |
| C37 | Manage token/context budget | High | Covered | ADOPTED | context budget gate |
| C38 | Tune model selection and cost | Medium | Partial | DEFERRED | handled at platform/operator level |
| C39 | Use plugins for IDE integration | Low | Not direct | DEFERRED | out of scope for repo governance |
| C40 | Use MCP for extra integrations | Low | Not used | DEFERRED | no current dependency |
| C41 | Use voice input | Low | Not applicable | REJECTED | no relevance to engineering outcomes |
| C42 | Be strict and explicit in prompting | High | Covered | ADOPTED | request contract + hard rejection rules |
| C43 | Set coding conventions and quality bar | High | Covered | ADOPTED | style/taste/logging/architecture validators |
| C44 | Avoid ping-pong and repetitive loops | High | Covered | ADOPTED | same-path cap + forced reset/new search |
| C45 | Keep learning and share templates | High | Covered | ADOPTED | memory registry + workflow docs |

---

## Implemented deltas from this mapping
1. Enforced repeated-incident learning quality:
   - `configs/agent_incident_policy.yaml` now requires `incident_signature` for new incidents.
   - `scripts/validate_agent_memory.py` now blocks repeated signatures without changed `prevention_change` and `prevention_check`.
2. Enforced repetition cap consistency:
   - `scripts/validate_task_request_contract.py` now validates numeric `Max Same-Path Attempts` and checks it against policy.
3. Process docs synchronized with the new controls:
   - `AGENTS.md`, `docs/DEV_WORKFLOW.md`, `docs/checklists/task-request-contract.md`, `docs/runbooks/governance-remediation.md`.

## Explicitly deferred
- Claude-CLI-specific features (custom slash commands, plugins, MCP-only flows, voice input) are deferred or rejected where they do not improve risk/quality invariants in this repository.
