from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from agent_process_telemetry import (
    TASK_OUTCOMES_REMEDIATION_DOC,
    build_task_outcome_record,
    default_events_path,
    default_session_handoff_path,
    default_state_path,
    default_task_outcomes_path,
    get_active_task,
    get_repo_root,
    is_terminal_outcome_status,
    load_state,
    normalize_task_outcome,
    parse_session_handoff,
    reconcile_legacy_process_storage,
    record_task_end,
    upsert_task_outcome,
)


def _infer_linked_plan_id(path: Path) -> str | None:
    if not path.exists():
        return None
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    active_ids = [
        str(row.get("id", "")).strip()
        for row in items
        if isinstance(row, dict) and str(row.get("status", "")).strip() == "active"
    ]
    if len(active_ids) == 1:
        return active_ids[0]
    return None


def run(
    *,
    session_handoff_path: Path,
    state_path: Path,
    events_path: Path,
    task_outcomes_path: Path,
) -> int:
    repo_root = get_repo_root()
    state = reconcile_legacy_process_storage(
        repo_root,
        events_path=events_path,
        state_path=state_path,
    )
    active = get_active_task(state, repo_root)
    if not isinstance(active, dict):
        print("task outcome sync skipped: active task telemetry state not found")
        return 0

    handoff = parse_session_handoff(session_handoff_path)
    task_outcome = normalize_task_outcome(handoff.get("task_outcome", {}))
    if is_terminal_outcome_status(task_outcome["outcome_status"]):
        record_task_end(
            events_path=events_path,
            state_path=state_path,
            handoff_path=session_handoff_path,
            task_outcome=task_outcome,
        )
        state = load_state(state_path)
        active = get_active_task(state, repo_root)
        if not isinstance(active, dict):
            print("task outcome sync failed: active task disappeared after closeout")
            print(f"remediation: see {TASK_OUTCOMES_REMEDIATION_DOC}")
            return 1

    record = build_task_outcome_record(active, task_outcome)
    if (
        record["improvement_action"] not in {"none", "pending"}
        and not record.get("linked_plan_id")
        and not record.get("linked_memory_id")
    ):
        inferred_plan_id = _infer_linked_plan_id(Path("plans/PLANS.yaml"))
        if inferred_plan_id:
            record["linked_plan_id"] = inferred_plan_id
    upsert_task_outcome(task_outcomes_path, record)
    print(
        "task outcomes sync: OK "
        f"(task_id={record['task_id']} outcome_status={record['outcome_status']})"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync current task outcome into memory/task_outcomes.yaml.")
    parser.add_argument("--session-handoff-path", default=str(default_session_handoff_path()))
    parser.add_argument("--state-path", default=str(default_state_path()))
    parser.add_argument("--events-path", default=str(default_events_path()))
    parser.add_argument("--task-outcomes-path", default=str(default_task_outcomes_path()))
    args = parser.parse_args()
    sys.exit(
        run(
            session_handoff_path=Path(args.session_handoff_path),
            state_path=Path(args.state_path),
            events_path=Path(args.events_path),
            task_outcomes_path=Path(args.task_outcomes_path),
        )
    )


if __name__ == "__main__":
    main()
