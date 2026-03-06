from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import yaml

from context_router import route_files


TERMINAL_OUTCOME_STATUSES = {"completed", "partial", "blocked"}
ALLOWED_OUTCOME_STATUSES = TERMINAL_OUTCOME_STATUSES | {"in_progress"}
ALLOWED_DECISION_QUALITY = {
    "pending",
    "correct_first_time",
    "correct_after_replan",
    "wrong_path",
    "partial_outcome",
    "environment_blocked",
}
ALLOWED_ROUTE_MATCH = {"pending", "matched", "expanded", "mismatched"}
ALLOWED_PRIMARY_REWORK_CAUSES = {
    "none",
    "wrong_path",
    "context_gap",
    "environment",
    "test_gap",
    "workflow_gap",
    "architecture_gap",
    "requirements_gap",
    "other",
}
ALLOWED_IMPROVEMENT_ACTIONS = {
    "pending",
    "none",
    "docs",
    "validator",
    "skill",
    "env",
    "architecture",
    "workflow",
    "test",
}
ROLLING_WINDOW_SIZE = 20
TASK_OUTCOMES_REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"
MARKDOWN_KEY_RE = re.compile(r"[^a-z0-9]+")

ROLLING_THRESHOLDS = {
    "decision-quality": {
        "correct_first_time_pct": ("ge", 0.70),
    },
    "context-efficiency": {
        "start_match_pct": ("ge", 0.75),
        "context_expansion_rate": ("le", 0.25),
    },
    "self-learning": {
        "repeat_error_rate": ("le", 0.15),
        "environment_blocker_rate": ("le", 0.20),
    },
}


def default_process_root() -> Path:
    return Path(os.getenv("MOEX_CARRY_AGENT_PROCESS_ROOT", ".runlogs/agent-process"))


def default_events_path() -> Path:
    return Path(os.getenv("MOEX_CARRY_AGENT_PROCESS_EVENTS", default_process_root() / "task-events.jsonl"))


def default_state_path() -> Path:
    return Path(os.getenv("MOEX_CARRY_AGENT_PROCESS_STATE", default_process_root() / "state.json"))


def default_session_handoff_path() -> Path:
    return Path(os.getenv("MOEX_CARRY_SESSION_HANDOFF_PATH", "docs/session_handoff.md"))


def default_task_outcomes_path() -> Path:
    return Path(os.getenv("MOEX_CARRY_TASK_OUTCOMES_PATH", "memory/task_outcomes.yaml"))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_utc_iso() -> str:
    return now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _safe_ratio(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _percentile(values: list[int], percentile_value: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    raw_index = percentile_value * (len(ordered) - 1)
    lower = int(raw_index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = raw_index - lower
    return int(round(ordered[lower] * (1 - weight) + ordered[upper] * weight))


def _normalize_markdown_key(value: str) -> str:
    lowered = value.strip().lower()
    return MARKDOWN_KEY_RE.sub("_", lowered).strip("_")


def _find_heading_line(lines: list[str], heading: str) -> int:
    for idx, raw in enumerate(lines):
        if raw.strip() == heading:
            return idx
    return -1


def _section_lines(lines: list[str], heading: str) -> list[str]:
    start = _find_heading_line(lines, heading)
    if start < 0:
        return []
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if lines[idx].strip().startswith("## "):
            end = idx
            break
    return lines[start + 1 : end]


def _parse_bullet_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw in lines:
        stripped = raw.strip()
        if not stripped.startswith("- "):
            continue
        body = stripped[2:]
        if ":" not in body:
            continue
        key, value = body.split(":", 1)
        fields[_normalize_markdown_key(key)] = value.strip()
    return fields


def _section_text(lines: list[str], heading: str) -> str:
    section = _section_lines(lines, heading)
    flattened: list[str] = []
    for raw in section:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            flattened.append(stripped[2:].strip())
        else:
            flattened.append(stripped)
    return " ".join(flattened).strip()


def parse_session_handoff(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "goal_text": "",
            "goal_lines": [],
            "contract": {},
            "task_outcome": {},
        }
    lines = path.read_text(encoding="utf-8").splitlines()
    return {
        "goal_text": _section_text(lines, "## Goal"),
        "goal_lines": _section_lines(lines, "## Goal"),
        "contract": _parse_bullet_fields(_section_lines(lines, "## Task Request Contract")),
        "task_outcome": _parse_bullet_fields(_section_lines(lines, "## Task Outcome")),
    }


def split_contexts(raw: str | None) -> list[str]:
    if raw is None:
        return []
    normalized = str(raw).strip()
    if not normalized or normalized.lower() in {"pending", "none"}:
        return []
    return [item.strip() for item in normalized.split(",") if item.strip()]


def is_terminal_outcome_status(value: str | None) -> bool:
    return str(value or "").strip().lower() in TERMINAL_OUTCOME_STATUSES


def normalize_task_outcome(fields: dict[str, str]) -> dict[str, Any]:
    outcome_status = fields.get("outcome_status", "in_progress").strip().lower() or "in_progress"
    decision_quality = fields.get("decision_quality", "pending").strip().lower() or "pending"
    route_match = fields.get("route_match", "pending").strip().lower() or "pending"
    primary_rework_cause = (
        fields.get("primary_rework_cause", "none").strip().lower() or "none"
    )
    incident_signature = fields.get("incident_signature", "none").strip() or "none"
    improvement_action = fields.get("improvement_action", "pending").strip().lower() or "pending"
    improvement_artifact = fields.get("improvement_artifact", "pending").strip() or "pending"
    linked_plan_id = fields.get("linked_plan_id", "").strip()
    linked_memory_id = fields.get("linked_memory_id", "").strip()
    return {
        "outcome_status": outcome_status,
        "decision_quality": decision_quality,
        "final_contexts": split_contexts(fields.get("final_contexts", "")),
        "route_match": route_match,
        "primary_rework_cause": primary_rework_cause,
        "incident_signature": incident_signature,
        "improvement_action": improvement_action,
        "improvement_artifact": improvement_artifact,
        "linked_plan_id": linked_plan_id or None,
        "linked_memory_id": linked_memory_id or None,
    }


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(default or {})
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return dict(default or {})
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML object in {path.as_posix()}")
    return payload


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=False, sort_keys=False),
        encoding="utf-8",
    )


def get_repo_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError("not inside a git repository")
    return Path(completed.stdout.strip()).resolve()


def _run_git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def get_current_branch(repo_root: Path) -> str:
    return _run_git(repo_root, "branch", "--show-current") or "<detached>"


def get_head_sha(repo_root: Path) -> str:
    return _run_git(repo_root, "rev-parse", "HEAD")


def _deduplicate(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.replace("\\", "/").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def collect_working_tree_changes(repo_root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return []
    paths: list[str] = []
    for raw in completed.stdout.splitlines():
        if not raw:
            continue
        text = raw.rstrip()
        path_text = text[3:] if len(text) > 3 else ""
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1]
        if path_text:
            paths.append(path_text.strip())
    return _deduplicate(paths)


def collect_diff_between_refs(repo_root: Path, base_sha: str, head_sha: str) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", base_sha, head_sha],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return []
    return _deduplicate([line.strip() for line in completed.stdout.splitlines() if line.strip()])


def compute_diff_fingerprint(repo_root: Path, changed_files: list[str]) -> str:
    digest = hashlib.sha1()
    for path_text in sorted(changed_files):
        digest.update(path_text.encode("utf-8"))
        candidate = repo_root / path_text
        if candidate.exists() and candidate.is_file():
            try:
                digest.update(candidate.read_bytes())
            except OSError:
                digest.update(b"<unreadable>")
        else:
            digest.update(b"<missing>")
    return digest.hexdigest()


def is_non_trivial_diff(changed_files: list[str]) -> bool:
    trivial_paths = {
        "docs/session_handoff.md",
        "memory/task_outcomes.yaml",
        ".runlogs/agent-process/task-events.jsonl",
        ".runlogs/agent-process/state.json",
    }
    trivial_prefixes = (".runlogs/",)
    for path_text in changed_files:
        normalized = path_text.replace("\\", "/")
        if normalized in trivial_paths:
            continue
        if normalized.startswith(trivial_prefixes):
            continue
        return True
    return False


def resolve_context_route(repo_root: Path, handoff_path: Path, changed_files: list[str]) -> dict[str, Any]:
    handoff_text = handoff_path.read_text(encoding="utf-8") if handoff_path.exists() else ""
    request_text = os.getenv("MOEX_CARRY_CONTEXT_ROUTER_REQUEST", "").strip()
    target_modules = [
        part.strip()
        for part in os.getenv("MOEX_CARRY_CONTEXT_ROUTER_TARGET_MODULES", "").split(",")
        if part.strip()
    ]
    result = route_files(
        changed_files,
        request_text=request_text,
        target_modules=target_modules,
        session_handoff_text=handoff_text,
    )
    contexts = [
        entry["id"]
        for entry in result.get("contexts", [])
        if isinstance(entry, dict) and str(entry.get("id", "")).strip()
    ]
    return {
        "primary_context": result.get("primary_context"),
        "contexts": contexts,
        "intent_sources": list(result.get("intent_sources", [])),
        "unmapped_files": list(result.get("unmapped_files", [])),
        "recommendations": list(result.get("recommendations", [])),
    }


def _active_task_descriptor(branch: str, handoff: dict[str, Any]) -> str:
    contract = handoff.get("contract", {})
    objective = ""
    if isinstance(contract, dict):
        objective = str(contract.get("objective", "")).strip()
    goal_text = str(handoff.get("goal_text", "")).strip()
    return " ".join(part for part in (branch, goal_text, objective) if part).strip()


def build_task_key(branch: str, handoff: dict[str, Any]) -> str:
    descriptor = _active_task_descriptor(branch, handoff).lower() or branch.lower()
    normalized = " ".join(descriptor.split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def build_task_id(task_key: str) -> str:
    return f"APT-{now_utc().strftime('%Y%m%dT%H%M%SZ')}-{task_key[:8]}"


def classify_goal_class(start_primary_context: str | None) -> str:
    context = str(start_primary_context or "").strip()
    if not context:
        return "unknown"
    if context.startswith("CTX-"):
        return context[4:].lower()
    return context.lower()


def load_task_outcomes(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "updated_at": date.today().isoformat(), "items": []}
    payload = load_yaml(path)
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    return {
        "version": payload.get("version", 1),
        "updated_at": str(payload.get("updated_at", date.today().isoformat())),
        "items": items,
    }


def write_task_outcomes(path: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = date.today().isoformat()
    write_yaml(path, payload)


def upsert_task_outcome(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    payload = load_task_outcomes(path)
    items = list(payload.get("items", []))
    updated = False
    for idx, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get("task_id") == record.get("task_id"):
            items[idx] = record
            updated = True
            break
    if not updated:
        items.append(record)
    payload["version"] = 1
    payload["items"] = items
    write_task_outcomes(path, payload)
    return payload


def load_state(path: Path) -> dict[str, Any]:
    state = load_json(path, default={"version": 1})
    if "version" not in state:
        state["version"] = 1
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    state["version"] = 1
    write_json(path, state)


def _base_active_task_payload(
    *,
    task_id: str,
    task_key: str,
    branch: str,
    head_sha: str,
    start_primary_context: str | None,
    start_contexts: list[str],
    intent_sources: list[str],
    unmapped_files: list[str],
    baseline_changed_files: list[str],
    baseline_diff_hash: str,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "task_key": task_key,
        "started_at": now_utc_iso(),
        "branch": branch,
        "head_sha": head_sha,
        "start_primary_context": start_primary_context or "unknown",
        "start_contexts": list(start_contexts),
        "intent_sources": list(intent_sources),
        "unmapped_files_count": len(unmapped_files),
        "baseline_changed_files": list(baseline_changed_files),
        "baseline_diff_hash": baseline_diff_hash,
        "last_seen_diff_hash": baseline_diff_hash,
        "last_path_signature": "|".join(sorted(baseline_changed_files)),
        "current_same_path_attempts": 0,
        "max_same_path_attempts_observed": 0,
        "first_patch_at": None,
        "time_to_first_patch_sec": None,
        "first_patch_changed_files_count": 0,
        "first_patch_changed_contexts": [],
        "closed_at": None,
        "outcome_status": "in_progress",
        "decision_quality": "pending",
        "route_match": "pending",
        "primary_rework_cause": "none",
        "incident_signature": "none",
        "improvement_action": "pending",
        "improvement_artifact": "pending",
    }


def start_task(*, events_path: Path, state_path: Path, handoff_path: Path) -> tuple[bool, dict[str, Any]]:
    repo_root = get_repo_root()
    state = load_state(state_path)
    handoff = parse_session_handoff(handoff_path)
    branch = get_current_branch(repo_root)
    task_key = build_task_key(branch, handoff)
    active = state.get("active_task")
    if (
        isinstance(active, dict)
        and active.get("task_key") == task_key
        and active.get("branch") == branch
        and not active.get("closed_at")
    ):
        return False, active

    changed_files = collect_working_tree_changes(repo_root)
    route = resolve_context_route(repo_root, handoff_path, changed_files)
    task_id = build_task_id(task_key)
    baseline_diff_hash = compute_diff_fingerprint(repo_root, changed_files)
    active_task = _base_active_task_payload(
        task_id=task_id,
        task_key=task_key,
        branch=branch,
        head_sha=get_head_sha(repo_root),
        start_primary_context=str(route.get("primary_context") or "unknown"),
        start_contexts=list(route.get("contexts", [])),
        intent_sources=list(route.get("intent_sources", [])),
        unmapped_files=list(route.get("unmapped_files", [])),
        baseline_changed_files=changed_files,
        baseline_diff_hash=baseline_diff_hash,
    )
    append_jsonl(
        events_path,
        {
            "event_type": "task_start",
            "task_id": task_id,
            "started_at": active_task["started_at"],
            "branch": active_task["branch"],
            "head_sha": active_task["head_sha"],
            "start_primary_context": active_task["start_primary_context"],
            "start_contexts": active_task["start_contexts"],
            "intent_sources": active_task["intent_sources"],
            "unmapped_files_count": active_task["unmapped_files_count"],
        },
    )
    state["active_task"] = active_task
    save_state(state_path, state)
    return True, active_task


def record_first_patch(*, events_path: Path, state_path: Path, handoff_path: Path) -> tuple[bool, dict[str, Any] | None]:
    repo_root = get_repo_root()
    state = load_state(state_path)
    active = state.get("active_task")
    if not isinstance(active, dict) or active.get("closed_at"):
        return False, None

    changed_files = collect_working_tree_changes(repo_root)
    if not changed_files:
        return False, active

    diff_hash = compute_diff_fingerprint(repo_root, changed_files)
    if active.get("first_patch_at") is None:
        if diff_hash == active.get("baseline_diff_hash"):
            return False, active
        route = resolve_context_route(repo_root, handoff_path, changed_files)
        started_at = parse_iso_datetime(str(active.get("started_at", "")))
        elapsed = 0
        if started_at is not None:
            elapsed = int((now_utc() - started_at).total_seconds())
        active["first_patch_at"] = now_utc_iso()
        active["time_to_first_patch_sec"] = max(elapsed, 0)
        active["first_patch_changed_files_count"] = len(changed_files)
        active["first_patch_changed_contexts"] = list(route.get("contexts", []))
        active["last_seen_diff_hash"] = diff_hash
        active["last_path_signature"] = "|".join(sorted(changed_files))
        active["current_same_path_attempts"] = 1
        active["max_same_path_attempts_observed"] = 1
        append_jsonl(
            events_path,
            {
                "event_type": "first_patch",
                "task_id": active["task_id"],
                "timestamp": active["first_patch_at"],
                "changed_files_count": len(changed_files),
                "changed_contexts": list(route.get("contexts", [])),
                "time_to_first_patch_sec": active["time_to_first_patch_sec"],
            },
        )
        state["active_task"] = active
        save_state(state_path, state)
        return True, active

    if diff_hash == active.get("last_seen_diff_hash"):
        return False, active

    path_signature = "|".join(sorted(changed_files))
    if path_signature == active.get("last_path_signature"):
        active["current_same_path_attempts"] = int(active.get("current_same_path_attempts", 1)) + 1
    else:
        active["current_same_path_attempts"] = 1
        active["last_path_signature"] = path_signature
    active["max_same_path_attempts_observed"] = max(
        int(active.get("max_same_path_attempts_observed", 1)),
        int(active.get("current_same_path_attempts", 1)),
    )
    active["last_seen_diff_hash"] = diff_hash
    state["active_task"] = active
    save_state(state_path, state)
    return False, active


def record_task_end(
    *,
    events_path: Path,
    state_path: Path,
    handoff_path: Path,
    task_outcome: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    state = load_state(state_path)
    active = state.get("active_task")
    if not isinstance(active, dict):
        return False, None
    if active.get("closed_at"):
        return False, active

    outcome = task_outcome or normalize_task_outcome(parse_session_handoff(handoff_path)["task_outcome"])
    if not is_terminal_outcome_status(str(outcome.get("outcome_status"))):
        return False, active

    closed_at = now_utc_iso()
    active["closed_at"] = closed_at
    active["outcome_status"] = outcome["outcome_status"]
    active["decision_quality"] = outcome["decision_quality"]
    active["route_match"] = outcome["route_match"]
    active["primary_rework_cause"] = outcome["primary_rework_cause"]
    active["incident_signature"] = outcome["incident_signature"]
    active["improvement_action"] = outcome["improvement_action"]
    active["improvement_artifact"] = outcome["improvement_artifact"]
    active["final_contexts"] = list(outcome.get("final_contexts", []))
    append_jsonl(
        events_path,
        {
            "event_type": "task_end",
            "task_id": active["task_id"],
            "closed_at": closed_at,
            "outcome_status": active["outcome_status"],
            "decision_quality": active["decision_quality"],
            "final_contexts": active.get("final_contexts", []),
            "route_match": active["route_match"],
            "same_path_attempts": int(active.get("max_same_path_attempts_observed", 0) or 0),
            "primary_rework_cause": active["primary_rework_cause"],
            "incident_signature": active["incident_signature"],
            "improvement_action": active["improvement_action"],
            "improvement_artifact": active["improvement_artifact"],
        },
    )
    state["active_task"] = active
    save_state(state_path, state)
    return True, active


def build_task_outcome_record(active_task: dict[str, Any], task_outcome: dict[str, Any]) -> dict[str, Any]:
    closed_at = active_task.get("closed_at") if is_terminal_outcome_status(task_outcome["outcome_status"]) else None
    return {
        "task_id": str(active_task.get("task_id", "")).strip(),
        "closed_at": closed_at,
        "branch": str(active_task.get("branch", "")).strip(),
        "goal_class": classify_goal_class(str(active_task.get("start_primary_context", ""))),
        "start_primary_context": str(active_task.get("start_primary_context", "unknown")),
        "start_contexts": list(active_task.get("start_contexts", [])),
        "final_contexts": list(task_outcome.get("final_contexts", [])),
        "route_match": task_outcome["route_match"],
        "time_to_first_patch_sec": active_task.get("time_to_first_patch_sec"),
        "same_path_attempts": max(int(active_task.get("max_same_path_attempts_observed", 0) or 0), 1),
        "decision_quality": task_outcome["decision_quality"],
        "primary_rework_cause": task_outcome["primary_rework_cause"],
        "incident_signature": task_outcome["incident_signature"],
        "improvement_action": task_outcome["improvement_action"],
        "improvement_artifact": task_outcome["improvement_artifact"],
        "linked_plan_id": task_outcome.get("linked_plan_id"),
        "linked_memory_id": task_outcome.get("linked_memory_id"),
        "outcome_status": task_outcome["outcome_status"],
        "unmapped_files_count": int(active_task.get("unmapped_files_count", 0) or 0),
        "intent_sources": list(active_task.get("intent_sources", [])),
    }


def _normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": str(raw.get("task_id", "")).strip(),
        "closed_at": raw.get("closed_at"),
        "branch": str(raw.get("branch", "")).strip(),
        "goal_class": str(raw.get("goal_class", "unknown")).strip() or "unknown",
        "start_primary_context": str(raw.get("start_primary_context", "unknown")).strip() or "unknown",
        "start_contexts": [str(item).strip() for item in raw.get("start_contexts", []) if str(item).strip()],
        "final_contexts": [str(item).strip() for item in raw.get("final_contexts", []) if str(item).strip()],
        "route_match": str(raw.get("route_match", "pending")).strip().lower() or "pending",
        "time_to_first_patch_sec": raw.get("time_to_first_patch_sec"),
        "same_path_attempts": int(raw.get("same_path_attempts", 1) or 1),
        "decision_quality": str(raw.get("decision_quality", "pending")).strip().lower() or "pending",
        "primary_rework_cause": str(raw.get("primary_rework_cause", "none")).strip().lower() or "none",
        "incident_signature": str(raw.get("incident_signature", "none")).strip() or "none",
        "improvement_action": str(raw.get("improvement_action", "pending")).strip().lower() or "pending",
        "improvement_artifact": str(raw.get("improvement_artifact", "pending")).strip() or "pending",
        "linked_plan_id": str(raw.get("linked_plan_id", "")).strip() or None,
        "linked_memory_id": str(raw.get("linked_memory_id", "")).strip() or None,
        "outcome_status": str(raw.get("outcome_status", "in_progress")).strip().lower() or "in_progress",
        "unmapped_files_count": int(raw.get("unmapped_files_count", 0) or 0),
        "intent_sources": [str(item).strip() for item in raw.get("intent_sources", []) if str(item).strip()],
    }


def completed_task_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items", [])
    records: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        record = _normalize_record(raw)
        if not is_terminal_outcome_status(record["outcome_status"]):
            continue
        if not record.get("closed_at"):
            continue
        records.append(record)
    records.sort(
        key=lambda item: parse_iso_datetime(str(item.get("closed_at", ""))) or datetime.min.replace(tzinfo=timezone.utc)
    )
    return records


def _decision_quality_by_goal_class(window: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in window:
        grouped[str(record.get("goal_class", "unknown"))].append(record)
    result: dict[str, dict[str, float | int]] = {}
    for goal_class, rows in sorted(grouped.items()):
        total = len(rows)
        result[goal_class] = {
            "tasks": total,
            "correct_first_time_pct": _safe_ratio(
                sum(1 for row in rows if row["decision_quality"] == "correct_first_time"),
                total,
            ),
            "correct_after_replan_pct": _safe_ratio(
                sum(1 for row in rows if row["decision_quality"] == "correct_after_replan"),
                total,
            ),
        }
    return result


def _enrich_repeat_markers(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_signatures: set[str] = set()
    enriched: list[dict[str, Any]] = []
    for record in records:
        clone = dict(record)
        signature = str(record.get("incident_signature", "")).strip()
        repeated = bool(signature and signature != "none" and signature in seen_signatures)
        clone["is_repeat_error"] = repeated
        if signature and signature != "none":
            seen_signatures.add(signature)
        enriched.append(clone)
    return enriched


def compute_process_rollup(payload: dict[str, Any], window_size: int = ROLLING_WINDOW_SIZE) -> dict[str, Any]:
    completed = _enrich_repeat_markers(completed_task_records(payload))
    current_window = completed[-window_size:] if window_size > 0 else list(completed)
    previous_window = completed[-2 * window_size : -window_size] if window_size > 0 else []
    total = len(current_window)
    same_path_values = [int(row.get("same_path_attempts", 1) or 1) for row in current_window]
    timing_values = [
        int(row.get("time_to_first_patch_sec", 0) or 0)
        for row in current_window
        if row.get("time_to_first_patch_sec") is not None
    ]
    current_metrics = {
        "correct_first_time_pct": _safe_ratio(
            sum(1 for row in current_window if row["decision_quality"] == "correct_first_time"),
            total,
        ),
        "correct_after_replan_pct": _safe_ratio(
            sum(1 for row in current_window if row["decision_quality"] == "correct_after_replan"),
            total,
        ),
        "wrong_path_rate": _safe_ratio(
            sum(1 for row in current_window if row["decision_quality"] == "wrong_path"),
            total,
        ),
        "rework_rate": _safe_ratio(
            sum(1 for row in current_window if row["decision_quality"] != "correct_first_time"),
            total,
        ),
        "decision_quality_by_goal_class": _decision_quality_by_goal_class(current_window),
        "start_resolution_pct": _safe_ratio(
            sum(1 for row in current_window if row["start_primary_context"] not in {"", "unknown"}),
            total,
        ),
        "start_match_pct": _safe_ratio(
            sum(1 for row in current_window if row["route_match"] == "matched"),
            total,
        ),
        "single_context_task_pct": _safe_ratio(
            sum(1 for row in current_window if len(row["final_contexts"]) == 1),
            total,
        ),
        "context_expansion_rate": _safe_ratio(
            sum(
                1
                for row in current_window
                if row["route_match"] == "expanded"
                or len(row["final_contexts"]) > max(len(row["start_contexts"]), 1)
            ),
            total,
        ),
        "unmapped_significant_file_rate": _safe_ratio(
            sum(1 for row in current_window if int(row.get("unmapped_files_count", 0) or 0) > 0),
            total,
        ),
        "median_time_to_first_patch_sec": int(median(timing_values)) if timing_values else 0,
        "repeat_error_rate": _safe_ratio(
            sum(1 for row in current_window if row.get("is_repeat_error")),
            total,
        ),
        "environment_blocker_rate": _safe_ratio(
            sum(
                1
                for row in current_window
                if row["decision_quality"] == "environment_blocked"
                or row["primary_rework_cause"] == "environment"
            ),
            total,
        ),
        "same_path_attempts_p50": _percentile(same_path_values, 0.5),
        "same_path_attempts_p90": _percentile(same_path_values, 0.9),
    }

    previous_numeric_metrics: dict[str, float | int] = {}
    if previous_window:
        previous_rollup = compute_process_rollup({"items": previous_window}, window_size=len(previous_window))
        previous_numeric_metrics = previous_rollup["current_metrics"]

    deltas: dict[str, float | int] = {}
    for key, value in current_metrics.items():
        if isinstance(value, (int, float)) and key in previous_numeric_metrics and isinstance(
            previous_numeric_metrics[key], (int, float)
        ):
            deltas[key] = float(value) - float(previous_numeric_metrics[key])

    repeated_signatures = Counter(
        str(row["incident_signature"])
        for row in current_window
        if row.get("is_repeat_error") and row["incident_signature"] != "none"
    )
    signature_recurrence = Counter(
        str(row["incident_signature"])
        for row in current_window
        if row["incident_signature"] != "none"
    )
    environment_blockers = Counter(
        str(row["incident_signature"] or "environment/no-signature")
        for row in current_window
        if row["primary_rework_cause"] == "environment"
    )
    improvement_action_mix = Counter(
        str(row["improvement_action"])
        for row in current_window
        if row["improvement_action"] not in {"pending", ""}
    )
    threshold_results: dict[str, dict[str, Any]] = {}
    burn_in_complete = len(completed) >= window_size
    for dimension, rules in ROLLING_THRESHOLDS.items():
        dimension_status = {"ok": True, "checks": []}
        for metric_name, (op_name, threshold) in rules.items():
            actual = float(current_metrics.get(metric_name, 0.0))
            passed = actual >= threshold if op_name == "ge" else actual <= threshold
            if not passed:
                dimension_status["ok"] = False
            dimension_status["checks"].append(
                {
                    "metric": metric_name,
                    "operator": op_name,
                    "threshold": threshold,
                    "actual": actual,
                    "passed": passed,
                }
            )
        threshold_results[dimension] = dimension_status

    return {
        "completed_tasks_count": len(completed),
        "window_size": window_size,
        "current_window_count": total,
        "burn_in_complete": burn_in_complete,
        "current_metrics": current_metrics,
        "previous_metrics": previous_numeric_metrics,
        "deltas": deltas,
        "top_repeated_error_signatures": repeated_signatures.most_common(5),
        "repeat_signature_recurrence": signature_recurrence.most_common(5),
        "top_environment_blockers": environment_blockers.most_common(5),
        "tasks_with_wrong_path_or_partial": [
            row
            for row in current_window
            if row["decision_quality"] == "wrong_path"
            or row["decision_quality"] == "partial_outcome"
            or row["outcome_status"] == "partial"
        ],
        "improvement_actions_without_followup": [
            row
            for row in current_window
            if row["improvement_action"] not in {"none", "pending"}
            and not row.get("linked_plan_id")
            and not row.get("linked_memory_id")
        ],
        "improvement_action_mix": dict(sorted(improvement_action_mix.items())),
        "threshold_results": threshold_results,
    }


def render_rollup_markdown(rollup: dict[str, Any]) -> str:
    lines = [
        "# Process Improvement Rollup",
        "",
        f"- completed_tasks_count: {rollup['completed_tasks_count']}",
        f"- rolling_window_size: {rollup['window_size']}",
        f"- burn_in_complete: {rollup['burn_in_complete']}",
        "",
        "## Current Metrics",
        "",
        "| Metric | Value | Delta |",
        "| --- | --- | --- |",
    ]
    current_metrics = rollup["current_metrics"]
    deltas = rollup.get("deltas", {})
    for key, value in current_metrics.items():
        if isinstance(value, dict):
            continue
        if isinstance(value, float):
            value_text = f"{value:.2f}"
        else:
            value_text = str(value)
        delta_value = deltas.get(key)
        if isinstance(delta_value, float):
            delta_text = f"{delta_value:+.2f}"
        elif isinstance(delta_value, int):
            delta_text = f"{delta_value:+d}"
        else:
            delta_text = "n/a"
        lines.append(f"| `{key}` | {value_text} | {delta_text} |")

    lines.extend(
        [
            "",
            "## Thresholds",
            "",
            "| Dimension | Status | Checks |",
            "| --- | --- | --- |",
        ]
    )
    for dimension, payload in sorted(rollup["threshold_results"].items()):
        checks = ", ".join(
            f"{check['metric']} {check['operator']} {check['threshold']:.2f} (actual={check['actual']:.2f})"
            for check in payload["checks"]
        )
        status = "pass" if payload["ok"] or not rollup["burn_in_complete"] else "fail"
        if not rollup["burn_in_complete"]:
            status = "burn-in"
        lines.append(f"| `{dimension}` | {status} | {checks} |")

    def _append_ranked(title: str, items: list[tuple[str, int]]) -> None:
        lines.extend(["", f"## {title}", ""])
        if items:
            for name, count in items:
                lines.append(f"- `{name}`: {count}")
        else:
            lines.append("- none")

    _append_ranked("Top Repeated Error Signatures", list(rollup["top_repeated_error_signatures"]))
    _append_ranked("Repeat Signature Recurrence", list(rollup["repeat_signature_recurrence"]))
    _append_ranked("Top Environment Blockers", list(rollup["top_environment_blockers"]))

    lines.extend(["", "## Wrong Path Or Partial Tasks", ""])
    tasks = rollup["tasks_with_wrong_path_or_partial"]
    if tasks:
        for task in tasks:
            lines.append(
                "- "
                f"{task['task_id']} ({task['decision_quality']}, outcome={task['outcome_status']}, "
                f"route_match={task['route_match']})"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Improvement Actions Without Follow-Up", ""])
    missing = rollup["improvement_actions_without_followup"]
    if missing:
        for task in missing:
            lines.append(
                f"- {task['task_id']} action={task['improvement_action']} artifact={task['improvement_artifact']}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Improvement Action Mix", ""])
    mix = rollup["improvement_action_mix"]
    if mix:
        for name, count in sorted(mix.items()):
            lines.append(f"- `{name}`: {count}")
    else:
        lines.append("- none")

    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record and roll up agent process telemetry.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("start", "first-patch", "end"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--events-path", default=str(default_events_path()))
        sub.add_argument("--state-path", default=str(default_state_path()))
        sub.add_argument("--session-handoff-path", default=str(default_session_handoff_path()))

    rollup = subparsers.add_parser("rollup")
    rollup.add_argument("--task-outcomes-path", default=str(default_task_outcomes_path()))
    rollup.add_argument("--window-size", type=int, default=ROLLING_WINDOW_SIZE)
    rollup.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "start":
        created, active = start_task(
            events_path=Path(args.events_path),
            state_path=Path(args.state_path),
            handoff_path=Path(args.session_handoff_path),
        )
        if active is None:
            print("agent process telemetry: skipped (no active task)")
            return 0
        verb = "started" if created else "unchanged"
        print(
            "agent process telemetry: "
            f"{verb} task_id={active['task_id']} context={active['start_primary_context']}"
        )
        return 0

    if args.command == "first-patch":
        recorded, active = record_first_patch(
            events_path=Path(args.events_path),
            state_path=Path(args.state_path),
            handoff_path=Path(args.session_handoff_path),
        )
        if active is None:
            print("agent process telemetry: no active task")
            return 0
        if recorded:
            print(
                "agent process telemetry: "
                f"first_patch task_id={active['task_id']} "
                f"time_to_first_patch_sec={active['time_to_first_patch_sec']}"
            )
        else:
            print("agent process telemetry: first_patch no-op")
        return 0

    if args.command == "end":
        recorded, active = record_task_end(
            events_path=Path(args.events_path),
            state_path=Path(args.state_path),
            handoff_path=Path(args.session_handoff_path),
        )
        if active is None:
            print("agent process telemetry: no active task")
            return 0
        if recorded:
            print(
                "agent process telemetry: "
                f"ended task_id={active['task_id']} outcome={active['outcome_status']}"
            )
        else:
            print("agent process telemetry: end no-op")
        return 0

    payload = load_task_outcomes(Path(args.task_outcomes_path))
    rollup = compute_process_rollup(payload, window_size=args.window_size)
    if args.format == "markdown":
        print(render_rollup_markdown(rollup).rstrip())
    else:
        print(json.dumps(rollup, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
