# 0004 Context Telemetry and Long-Conversation Observability

## Status
Accepted

## Date
2026-03-09

## Context
The repository already tracks useful process signals:
- task start / first-patch / end lifecycle,
- session handoff and task outcome closeout,
- rolling process metrics such as `start_match_pct`, `context_expansion_rate`, and `correct_first_time_pct`,
- weekly process-improvement reporting and scorecards.

These signals are valuable, but they do not directly measure actual context cost.
They mainly describe process quality and routing discipline.

That leaves several blind spots:
- a task can stay in one context and still load a very large amount of code or tool output;
- long conversations can degrade through compaction, stale summaries, or partial recall without any first-class telemetry;
- current metrics do not distinguish direct context consumption from downstream quality outcomes;
- the system cannot tell whether a task was cheap because it was well-routed or because it under-read and got lucky.

We need a telemetry design that supports systematic improvement of agent behavior, especially for long-running conversations.

## Decision
Adopt a layered telemetry architecture with separate but linked signals for:
1. task lifecycle,
2. turn and conversation progression,
3. context acquisition cost,
4. summary and compaction lineage,
5. execution behavior,
6. final outcomes and governance rollups.

The design treats direct context-cost metrics and outcome-proxy metrics as different classes of evidence.
Both are required; neither replaces the other.

## Design Principles
- Measure direct cost and quality separately.
- Treat long-conversation continuity as a first-class observability problem.
- Prefer repository-native artifacts and deterministic local collection.
- Store counts, hashes, references, and bounded excerpts before raw content.
- Make telemetry resistant to gaming by pairing cost metrics with quality and recovery metrics.
- Keep one canonical event envelope and derive rollups from it instead of duplicating rules across scripts and reports.

## Telemetry Layers

| Layer | Purpose | Example events | Primary questions |
| --- | --- | --- | --- |
| Task lifecycle | Track one development task as the main unit of work | `task_started`, `first_patch_recorded`, `task_closed` | Did we start in the right place, patch quickly, and close correctly? |
| Turn / conversation | Track interaction growth and pacing inside a task | `turn_opened`, `turn_closed`, `assistant_summary_requested` | How long is the conversation and where do pivots happen? |
| Context acquisition | Track what was loaded into working context | `file_read`, `search_run`, `tool_output_captured`, `diff_inspected` | What did we actually read and how expensive was it? |
| Summary / compaction | Track memory compression and recall lineage | `summary_created`, `summary_applied`, `compaction_boundary_crossed`, `recall_check_failed` | Did long-chat compression preserve the task contract and critical facts? |
| Execution / edits | Track commands, edits, tests, and retries | `command_run`, `patch_applied`, `test_run`, `retry_triggered` | How much execution work happened before convergence? |
| Outcome / governance | Track durable resolution quality | `task_outcome_synced`, `process_rollup_computed`, `scorecard_evaluated` | Was the result correct, efficient, and stable? |

## Canonical Event Envelope
Every telemetry event should use the same envelope:

```yaml
event_id: string
ts_utc: ISO-8601 datetime
layer: task|turn|context|summary|execution|outcome
event_type: string
task_id: string
thread_id: string | null
turn_id: string | null
summary_id: string | null
parent_summary_id: string | null
branch: string
worktree_path: string
source: worktree_guard|lean_gate|ui|tooling|reporting
attributes: object
```

Rules:
- `task_id` remains the join key for governance.
- `thread_id` identifies the conversation lineage across long chats.
- `turn_id` supports per-turn cost and pacing analysis.
- `summary_id` and `parent_summary_id` make compaction lineage explicit instead of opaque.
- `attributes` stays layer-specific.

## Long-Conversation Model
Long conversations are not just “many turns”.
They create a separate failure mode: summary drift.

The telemetry model therefore adds explicit long-conversation events:
- `summary_created`
- `summary_applied`
- `compaction_boundary_crossed`
- `summary_rehydrated_into_task`
- `recall_check_passed`
- `recall_check_failed`
- `handoff_refreshed_from_summary`

For each summary event we should record:
- summary size estimate,
- source turn range,
- source artifact references,
- whether it replaced prior context or augmented it,
- whether the summary preserved task objective, scope, blockers, and next step.

This enables derived long-chat metrics such as:
- summary depth,
- summary reuse rate,
- handoff refresh count,
- recall failure rate after compaction,
- summary lineage length before final patch,
- context-loss incidents per long conversation.

## Direct Context-Cost Metrics
These are the metrics we currently do not measure well enough and should treat as primary context telemetry:

- `unique_files_read_before_first_patch`
- `total_file_reads`
- `total_lines_read`
- `repeated_read_ratio`
- `search_queries_count`
- `tool_output_chars_total`
- `tool_output_chars_before_first_patch`
- `handoff_chars_loaded`
- `summary_chars_loaded`
- `context_artifacts_loaded_count`
- `context_cost_before_first_patch`
- `context_cost_total`

When exact token counts are unavailable, use a stable estimate:
- provider tokens when available,
- otherwise a deterministic character-to-token approximation recorded as `token_estimate`.

The design must always distinguish:
- `token_actual`
- `token_estimate`

so later analysis does not confuse the two.

## Outcome-Proxy Metrics
Existing metrics remain useful, but are explicitly classified as outcome proxies:
- `start_match_pct`
- `context_expansion_rate`
- `correct_first_time_pct`
- `same_path_attempts`
- `time_to_first_patch_sec`
- `repeat_error_rate`
- `environment_blocker_rate`

These should be kept because they measure the consequences of context behavior.
They must not be re-labeled as direct context cost.

## Derived Composite Metrics
The system should eventually support composite metrics that combine cost and quality:

- `context_cost_per_correct_first_time_task`
- `context_cost_before_first_patch_per_goal_class`
- `repeated_read_ratio_on_correct_first_time_tasks`
- `long_conversation_survival_rate`
- `summary_dependency_rate`
- `context_cost_delta_after_compaction`
- `cost_of_wrong_path`

This is the level where improvement work becomes meaningful.
Raw minimization of context cost alone is not the target.

## Storage and Retention
Use a three-tier model:

1. Raw event stream
   - location: `.runlogs/agent-process/context-events.jsonl`
   - purpose: append-only local event source

2. Durable task closeout ledger
   - location: `memory/task_outcomes.yaml`
   - purpose: keep compact per-task summary records for governance and PR review

3. Derived reports / snapshots
   - examples: process-improvement report, future context telemetry report, dashboard payloads
   - purpose: human review and threshold evaluation

Retention rules:
- keep raw event payloads bounded and local;
- store references and hashes for content-heavy artifacts when possible;
- avoid raw transcript persistence by default;
- only promote derived, bounded rollups into durable repository artifacts.

## Privacy and Minimization
By default, telemetry should not persist raw user conversation content unless strictly needed.

Preferred order:
1. counts,
2. hashes,
3. file or artifact references,
4. bounded excerpts,
5. raw content only if explicitly required and justified.

This matters more for long chats, where full transcript retention becomes both expensive and risky.

## Anti-Gaming Guardrails
The design must prevent “improving the metric by reading too little”.

Guardrails:
- never judge direct context-cost metrics without outcome metrics;
- segment results by task class (`ops`, `api-ui`, `contracts`, `research`, etc.);
- track under-reading symptoms such as wrong-path, late blocker discovery, and recall failure after compaction;
- flag suspicious patterns like very low context cost combined with high rework or wrong-path rates.

## Consumer Surfaces
This telemetry should feed multiple consumers:
- lean gate and local validators,
- process-improvement reports,
- quality scorecards,
- ops/process UI,
- future architecture and team-improvement reviews.

Consumer rule:
- all consumers derive from the same canonical event model and shared rollup code;
- no separate local interpretation of context telemetry should exist in parallel.

## Rollout Plan

### Phase 1: Direct context capture
- add event capture for file reads, searches, tool-output size, and turn boundaries;
- keep metrics advisory only.

### Phase 2: Long-conversation observability
- add summary and compaction lineage events;
- add recall-failure and handoff-refresh metrics.

### Phase 3: Derived rollups
- extend governance reports and dashboards with direct context-cost metrics;
- segment by task class and long-conversation status.

### Phase 4: Policy and thresholds
- only after data stabilizes, define thresholds for direct context-cost regressions;
- do not reuse current process-proxy thresholds blindly.

## Alternatives Considered
1. Keep using only current governance proxies.
   - Rejected: good for process discipline, weak for real context-cost truth.
2. Measure only provider token counts.
   - Rejected: incomplete across tools and misses structural long-chat failures.
3. Persist full chat transcripts as the main telemetry source.
   - Rejected: high cost, privacy risk, and unnecessary volume for most diagnostics.
4. Add many per-tool counters without a shared event model.
   - Rejected: easy to drift and hard to interpret across layers.

## Consequences
- Pros:
  - makes context optimization measurable instead of intuitive;
  - separates “used too much context” from “used context badly”;
  - gives long-conversation degradation a first-class model;
  - creates a clean phased path from design to implementation.
- Cons:
  - adds instrumentation complexity;
  - some metrics will start as estimates rather than exact tokens;
  - rollout needs careful anti-gaming discipline.

## Validation and Rollout
- Design validation:
  - `python scripts/validate_task_request_contract.py`
  - `python scripts/validate_session_handoff.py`
  - `python scripts/validate_plans.py`
  - `python scripts/validate_agent_memory.py`
  - `python scripts/run_lean_gate.py`
- Future implementation acceptance should include:
  - direct context-cost capture works in local runs,
  - long-conversation summary lineage is visible,
  - rollups separate direct-cost and outcome-proxy metrics,
  - dashboards and validators consume the same canonical rollup layer.
