from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from agent_process_telemetry import (
    ALLOWED_DECISION_QUALITY,
    ALLOWED_IMPROVEMENT_ACTIONS,
    ALLOWED_OUTCOME_STATUSES,
    ALLOWED_PRIMARY_REWORK_CAUSES,
    ALLOWED_ROUTE_MATCH,
    TASK_OUTCOMES_REMEDIATION_DOC,
    build_task_outcome_record,
    collect_diff_between_refs,
    collect_working_tree_changes,
    default_session_handoff_path,
    default_state_path,
    default_task_outcomes_path,
    get_active_task,
    get_repo_root,
    is_non_trivial_diff,
    is_terminal_outcome_status,
    load_task_outcomes,
    normalize_task_outcome,
    parse_session_handoff,
    reconcile_legacy_process_storage,
    resolve_context_route,
)


REQUIRED_TASK_OUTCOME_FIELDS = (
    "outcome_status",
    "decision_quality",
    "final_contexts",
    "route_match",
    "primary_rework_cause",
    "incident_signature",
    "improvement_action",
    "improvement_artifact",
)


def _load_incident_policy_max_attempts(path: Path) -> int | None:
    if not path.exists():
        return None
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return None
    incident = payload.get("incident") or {}
    if not isinstance(incident, dict):
        return None
    raw = incident.get("max_same_path_attempts")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _validate_ledger_shape(payload: dict[str, Any], errors: list[str]) -> None:
    if payload.get("version") != 1:
        errors.append(f"task outcomes ledger unsupported version: {payload.get('version')!r}")
    items = payload.get("items")
    if not isinstance(items, list):
        errors.append("task outcomes ledger field 'items' must be a list")
        return
    seen_ids: set[str] = set()
    for idx, raw in enumerate(items):
        label = f"items[{idx}]"
        if not isinstance(raw, dict):
            errors.append(f"{label} must be an object")
            continue
        task_id = str(raw.get("task_id", "")).strip()
        if not task_id:
            errors.append(f"{label} missing required field 'task_id'")
        elif task_id in seen_ids:
            errors.append(f"duplicate task_id in ledger: {task_id}")
        seen_ids.add(task_id)
        for field in ("branch", "goal_class", "start_primary_context", "improvement_artifact"):
            if not str(raw.get(field, "")).strip():
                errors.append(f"{label} missing required field '{field}'")
        if raw.get("route_match") not in ALLOWED_ROUTE_MATCH:
            errors.append(f"{label}.route_match invalid: {raw.get('route_match')!r}")
        if raw.get("decision_quality") not in ALLOWED_DECISION_QUALITY:
            errors.append(f"{label}.decision_quality invalid: {raw.get('decision_quality')!r}")
        if raw.get("outcome_status") not in ALLOWED_OUTCOME_STATUSES:
            errors.append(f"{label}.outcome_status invalid: {raw.get('outcome_status')!r}")
        if raw.get("primary_rework_cause") not in ALLOWED_PRIMARY_REWORK_CAUSES:
            errors.append(
                f"{label}.primary_rework_cause invalid: {raw.get('primary_rework_cause')!r}"
            )
        if raw.get("improvement_action") not in ALLOWED_IMPROVEMENT_ACTIONS:
            errors.append(f"{label}.improvement_action invalid: {raw.get('improvement_action')!r}")
        try:
            same_path_attempts = int(raw.get("same_path_attempts", 0))
            if same_path_attempts < 1:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{label}.same_path_attempts must be a positive integer")
        if raw.get("time_to_first_patch_sec") is not None:
            try:
                value = int(raw.get("time_to_first_patch_sec"))
                if value < 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"{label}.time_to_first_patch_sec must be null or non-negative integer")
        if not isinstance(raw.get("start_contexts", []), list):
            errors.append(f"{label}.start_contexts must be a list")
        if not isinstance(raw.get("final_contexts", []), list):
            errors.append(f"{label}.final_contexts must be a list")
        if "start_recommendations" in raw and not isinstance(raw.get("start_recommendations", []), list):
            errors.append(f"{label}.start_recommendations must be a list when present")
        if raw.get("improvement_action") not in {"none", "pending"}:
            if not raw.get("linked_plan_id") and not raw.get("linked_memory_id"):
                errors.append(
                    f"{label} improvement_action requires linked_plan_id or linked_memory_id"
                )
        if is_terminal_outcome_status(str(raw.get("outcome_status"))):
            if raw.get("closed_at") in {None, ""}:
                errors.append(f"{label}.closed_at is required for terminal outcomes")


def run(
    *,
    session_handoff_path: Path,
    state_path: Path,
    task_outcomes_path: Path,
    incident_policy_path: Path,
    focus: str | None,
    base_sha: str | None,
    head_sha: str | None,
) -> int:
    handoff = parse_session_handoff(session_handoff_path)
    task_outcome_section = handoff.get("task_outcome", {})
    task_outcome = normalize_task_outcome(task_outcome_section)
    repo_root = get_repo_root()
    changed_files = (
        collect_diff_between_refs(repo_root, base_sha, head_sha)
        if base_sha and head_sha
        else collect_working_tree_changes(repo_root)
    )
    non_trivial = is_non_trivial_diff(changed_files)
    ledger = load_task_outcomes(task_outcomes_path)
    events_path = state_path.parent / "task-events.jsonl"
    state = reconcile_legacy_process_storage(repo_root, events_path=events_path, state_path=state_path)
    active = get_active_task(state, repo_root)
    max_same_path_attempts = _load_incident_policy_max_attempts(incident_policy_path)

    errors_by_focus: dict[str, list[str]] = {
        "decision-quality": [],
        "context-efficiency": [],
        "self-learning": [],
    }

    missing_fields = [field for field in REQUIRED_TASK_OUTCOME_FIELDS if field not in task_outcome_section]
    if missing_fields:
        message = "Task Outcome section missing fields: " + ", ".join(missing_fields)
        for bucket in errors_by_focus.values():
            bucket.append(message)

    if task_outcome["outcome_status"] not in ALLOWED_OUTCOME_STATUSES:
        errors_by_focus["decision-quality"].append(
            f"Task Outcome outcome_status invalid: {task_outcome['outcome_status']!r}"
        )
    if task_outcome["decision_quality"] not in ALLOWED_DECISION_QUALITY:
        errors_by_focus["decision-quality"].append(
            f"Task Outcome decision_quality invalid: {task_outcome['decision_quality']!r}"
        )
    if task_outcome["route_match"] not in ALLOWED_ROUTE_MATCH:
        errors_by_focus["context-efficiency"].append(
            f"Task Outcome route_match invalid: {task_outcome['route_match']!r}"
        )
    if task_outcome["primary_rework_cause"] not in ALLOWED_PRIMARY_REWORK_CAUSES:
        errors_by_focus["self-learning"].append(
            f"Task Outcome primary_rework_cause invalid: {task_outcome['primary_rework_cause']!r}"
        )
    if task_outcome["improvement_action"] not in ALLOWED_IMPROVEMENT_ACTIONS:
        errors_by_focus["self-learning"].append(
            f"Task Outcome improvement_action invalid: {task_outcome['improvement_action']!r}"
        )

    ledger_shape_errors: list[str] = []
    _validate_ledger_shape(ledger, ledger_shape_errors)
    for message in ledger_shape_errors:
        for bucket in errors_by_focus.values():
            bucket.append(message)

    current_record = None
    if isinstance(active, dict):
        current_record = next(
            (
                row
                for row in ledger.get("items", [])
                if isinstance(row, dict) and row.get("task_id") == active.get("task_id")
            ),
            None,
        )

    if non_trivial:
        if base_sha and head_sha:
            if "docs/session_handoff.md" not in changed_files:
                for bucket in errors_by_focus.values():
                    bucket.append("non-trivial PR diff requires docs/session_handoff.md update")
            if "memory/task_outcomes.yaml" not in changed_files:
                for bucket in errors_by_focus.values():
                    bucket.append("non-trivial PR diff requires memory/task_outcomes.yaml update")
            if task_outcome["outcome_status"] == "in_progress":
                errors_by_focus["decision-quality"].append(
                    "non-trivial PR diff requires terminal Task Outcome status"
                )
        if not isinstance(active, dict) and not (base_sha and head_sha):
            for bucket in errors_by_focus.values():
                bucket.append(
                    "non-trivial diff detected but active task telemetry state is missing; "
                    "run worktree_guard -Action Check first"
                )
        if current_record is None and not (base_sha and head_sha):
            for bucket in errors_by_focus.values():
                bucket.append(
                    "non-trivial diff detected but memory/task_outcomes.yaml has no record for the active task"
                )

    if isinstance(active, dict):
        if max_same_path_attempts is not None:
            observed_attempts = int(active.get("max_same_path_attempts_observed", 0) or 0)
            if observed_attempts > max_same_path_attempts:
                errors_by_focus["self-learning"].append(
                    "same_path_attempts exceeds policy cap: "
                    f"{observed_attempts} > {max_same_path_attempts}"
                )
        if changed_files:
            route = resolve_context_route(repo_root, session_handoff_path, changed_files)
            unmapped_significant = [
                path
                for path in route["unmapped_files"]
                if path.startswith("src/moex_carry/") and path.endswith(".py")
            ]
            for path in unmapped_significant:
                errors_by_focus["context-efficiency"].append(
                    f"unmapped significant Python file in current diff: {path}"
                )

    if task_outcome["decision_quality"] not in {
        "pending",
        "correct_first_time",
        "correct_after_replan",
    } and task_outcome["improvement_action"] in {"none", "pending"}:
        errors_by_focus["decision-quality"].append(
            "decision_quality outside correct_* requires explicit improvement_action"
        )

    if task_outcome["improvement_action"] not in {"none", "pending"}:
        if not task_outcome.get("linked_plan_id") and not task_outcome.get("linked_memory_id"):
            errors_by_focus["self-learning"].append(
                "improvement_action requires linked_plan_id or linked_memory_id in Task Outcome"
            )

    if task_outcome["incident_signature"] != "none":
        previous_records = [
            row
            for row in ledger.get("items", [])
            if isinstance(row, dict)
            and row.get("incident_signature") == task_outcome["incident_signature"]
            and row.get("task_id") != (active.get("task_id") if isinstance(active, dict) else None)
        ]
        if previous_records:
            previous_artifacts = {
                str(row.get("improvement_artifact", "")).strip()
                for row in previous_records
                if str(row.get("improvement_artifact", "")).strip()
            }
            current_artifact = task_outcome["improvement_artifact"]
            if current_artifact in {"", "none", "pending"} or current_artifact in previous_artifacts:
                errors_by_focus["self-learning"].append(
                    "repeated incident_signature requires a new improvement_artifact"
                )
            if not task_outcome.get("linked_plan_id") and not task_outcome.get("linked_memory_id"):
                errors_by_focus["self-learning"].append(
                    "repeated incident_signature requires linked_plan_id or linked_memory_id"
                )

    if current_record is not None and isinstance(active, dict):
        expected_record = build_task_outcome_record(active, task_outcome)
        if expected_record["outcome_status"] != current_record.get("outcome_status"):
            errors_by_focus["decision-quality"].append(
                "current task outcome is out of sync with memory/task_outcomes.yaml"
            )
        if expected_record["route_match"] != current_record.get("route_match"):
            errors_by_focus["context-efficiency"].append(
                "current route_match is out of sync with memory/task_outcomes.yaml"
            )
        if expected_record["improvement_action"] != current_record.get("improvement_action"):
            errors_by_focus["self-learning"].append(
                "current improvement_action is out of sync with memory/task_outcomes.yaml"
            )
        if is_terminal_outcome_status(task_outcome["outcome_status"]) and not current_record.get("closed_at"):
            errors_by_focus["decision-quality"].append(
                "terminal task outcome requires closed_at in memory/task_outcomes.yaml"
            )
    elif base_sha and head_sha and non_trivial:
        terminal_records = [
            row
            for row in ledger.get("items", [])
            if isinstance(row, dict) and is_terminal_outcome_status(str(row.get("outcome_status")))
        ]
        if not terminal_records:
            errors_by_focus["decision-quality"].append(
                "non-trivial PR diff requires at least one terminal task outcome record"
            )

    if task_outcome["outcome_status"] == "in_progress" and task_outcome["decision_quality"] != "pending":
        errors_by_focus["decision-quality"].append(
            "in_progress Task Outcome must keep decision_quality=pending"
        )
    if task_outcome["outcome_status"] == "in_progress" and task_outcome["route_match"] != "pending":
        errors_by_focus["context-efficiency"].append(
            "in_progress Task Outcome must keep route_match=pending"
        )

    selected_errors = (
        errors_by_focus.get(focus, [])
        if focus
        else [item for bucket in errors_by_focus.values() for item in bucket]
    )

    if selected_errors:
        print("task outcomes validation failed:")
        for item in selected_errors:
            print(f"- {item}")
        print(f"remediation: see {TASK_OUTCOMES_REMEDIATION_DOC}")
        return 1

    print(
        "task outcomes validation: OK "
        f"(non_trivial_diff={non_trivial} ledger_items={len(ledger.get('items', []))})"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate task closeout fields and task outcome ledger.")
    parser.add_argument("--session-handoff-path", default=str(default_session_handoff_path()))
    parser.add_argument("--state-path", default=str(default_state_path()))
    parser.add_argument("--task-outcomes-path", default=str(default_task_outcomes_path()))
    parser.add_argument("--incident-policy-path", default="configs/agent_incident_policy.yaml")
    parser.add_argument("--focus", choices=("decision-quality", "context-efficiency", "self-learning"))
    parser.add_argument("--base-sha", default=None)
    parser.add_argument("--head-sha", default=None)
    args = parser.parse_args()
    sys.exit(
        run(
            session_handoff_path=Path(args.session_handoff_path),
            state_path=Path(args.state_path),
            task_outcomes_path=Path(args.task_outcomes_path),
            incident_policy_path=Path(args.incident_policy_path),
            focus=args.focus,
            base_sha=args.base_sha,
            head_sha=args.head_sha,
        )
    )


if __name__ == "__main__":
    main()
