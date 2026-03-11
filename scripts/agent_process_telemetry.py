from __future__ import annotations
# ruff: noqa: E402

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

try:
    from handoff_resolver import read_task_note_lines
except Exception:
    def read_task_note_lines(path: Path) -> tuple[Path, list[str], bool]:
        if not path.exists():
            return path, [], False
        text = path.read_text(encoding="utf-8")
        return path, text.splitlines(), False

try:
    from context_router import route_files
except Exception:
    def route_files(
        changed_files: list[str],
        *,
        request_text: str = "",
        target_modules: list[str] | None = None,
        session_handoff_text: str = "",
    ) -> dict[str, Any]:
        _ = (request_text, target_modules, session_handoff_text)
        has_scope = bool(changed_files)
        contexts = [{"id": "CTX-OPS"}] if has_scope else []
        return {
            "primary_context": "CTX-OPS" if has_scope else None,
            "contexts": contexts,
            "intent_sources": [],
            "cold_context_files": [],
            "unmapped_dependency_hints": {},
            "unmapped_files": [],
            "recommendations": [],
        }

try:
    from moex_carry.governance.process_reports import ROLLING_WINDOW_SIZE
except Exception:
    ROLLING_WINDOW_SIZE = 20


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
TASK_OUTCOMES_REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"
TASK_OUTCOME_POLICY_PATH = "configs/task_outcome_policy.yaml"
MARKDOWN_KEY_RE = re.compile(r"[^a-z0-9]+")
WINDOWS_ABS_PATH_RE = re.compile(r"^[a-zA-Z]:[\\/]")


def _resolve_path_from_repo(repo_root: Path, raw_path: str | Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return (repo_root / candidate).resolve()


def default_process_root() -> Path:
    override = os.getenv("MOEX_CARRY_AGENT_PROCESS_ROOT", "").strip()
    try:
        repo_root = get_repo_root()
    except RuntimeError:
        repo_root = Path.cwd().resolve()
    if override:
        return _resolve_path_from_repo(repo_root, override)
    common_dir = get_git_common_dir(repo_root)
    shared_root = common_dir.parent if common_dir.name == ".git" else repo_root
    return (shared_root / ".runlogs" / "agent-process").resolve()


def default_events_path() -> Path:
    override = os.getenv("MOEX_CARRY_AGENT_PROCESS_EVENTS", "").strip()
    if override:
        try:
            repo_root = get_repo_root()
        except RuntimeError:
            repo_root = Path.cwd().resolve()
        return _resolve_path_from_repo(repo_root, override)
    return default_process_root() / "task-events.jsonl"


def default_state_path() -> Path:
    override = os.getenv("MOEX_CARRY_AGENT_PROCESS_STATE", "").strip()
    if override:
        try:
            repo_root = get_repo_root()
        except RuntimeError:
            repo_root = Path.cwd().resolve()
        return _resolve_path_from_repo(repo_root, override)
    return default_process_root() / "state.json"


def default_session_handoff_path() -> Path:
    return Path(os.getenv("MOEX_CARRY_SESSION_HANDOFF_PATH", "docs/session_handoff.md"))


def default_task_outcomes_path() -> Path:
    return Path(os.getenv("MOEX_CARRY_TASK_OUTCOMES_PATH", "memory/task_outcomes.yaml"))


def default_task_outcome_policy_path() -> Path:
    return Path(os.getenv("MOEX_CARRY_TASK_OUTCOME_POLICY_PATH", TASK_OUTCOME_POLICY_PATH))


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


def _section_items(lines: list[str]) -> list[str]:
    items: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
        else:
            items.append(stripped)
    return items


def parse_session_handoff(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "goal_text": "",
            "goal_lines": [],
            "contract": {},
            "task_outcome": {},
            "blockers_text": "",
            "blockers_lines": [],
        }
    _resolved_path, lines, _is_pointer = read_task_note_lines(path)
    blockers_lines = _section_lines(lines, "## Blockers")
    return {
        "goal_text": _section_text(lines, "## Goal"),
        "goal_lines": _section_lines(lines, "## Goal"),
        "contract": _parse_bullet_fields(_section_lines(lines, "## Task Request Contract")),
        "task_outcome": _parse_bullet_fields(_section_lines(lines, "## Task Outcome")),
        "blockers_text": _section_text(lines, "## Blockers"),
        "blockers_lines": blockers_lines,
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


def _normalize_policy_phrase(value: str | None) -> str:
    collapsed = " ".join(str(value or "").strip().lower().split())
    return collapsed.rstrip(".!;:?").strip()


def load_task_outcome_status_policy(path: Path | None = None) -> dict[str, Any]:
    policy_path = path or default_task_outcome_policy_path()
    if not policy_path.is_absolute():
        try:
            repo_root = get_repo_root()
        except RuntimeError:
            repo_root = Path.cwd().resolve()
        policy_path = _resolve_path_from_repo(repo_root, policy_path)
    payload = load_yaml(policy_path)
    if not payload:
        raise ValueError(f"task outcome policy is missing or empty: {policy_path.as_posix()}")
    if payload.get("version") != 1:
        raise ValueError(f"task outcome policy unsupported version: {payload.get('version')!r}")

    raw_mapping = payload.get("status_by_decision_quality")
    if not isinstance(raw_mapping, dict):
        raise ValueError("task outcome policy must define status_by_decision_quality mapping")
    status_by_decision_quality = {
        str(key).strip().lower(): str(value).strip().lower()
        for key, value in raw_mapping.items()
        if str(key).strip()
    }
    missing_decisions = sorted(ALLOWED_DECISION_QUALITY - set(status_by_decision_quality))
    extra_decisions = sorted(set(status_by_decision_quality) - ALLOWED_DECISION_QUALITY)
    invalid_statuses = {
        key: value
        for key, value in status_by_decision_quality.items()
        if value not in ALLOWED_OUTCOME_STATUSES
    }
    if missing_decisions:
        raise ValueError(
            "task outcome policy missing decision_quality mapping for: "
            + ", ".join(missing_decisions)
        )
    if extra_decisions:
        raise ValueError(
            "task outcome policy has unsupported decision_quality keys: "
            + ", ".join(extra_decisions)
        )
    if invalid_statuses:
        rendered = ", ".join(f"{key}->{value}" for key, value in sorted(invalid_statuses.items()))
        raise ValueError(f"task outcome policy has invalid mapped statuses: {rendered}")

    raw_no_blocker_markers = payload.get("no_blocker_markers")
    if not isinstance(raw_no_blocker_markers, list):
        raise ValueError("task outcome policy must define no_blocker_markers list")
    no_blocker_markers = {
        normalized
        for normalized in (_normalize_policy_phrase(str(item)) for item in raw_no_blocker_markers)
        if normalized
    }
    if not no_blocker_markers:
        raise ValueError("task outcome policy no_blocker_markers list must not be empty")

    return {
        "path": str(policy_path),
        "status_by_decision_quality": status_by_decision_quality,
        "blocked_requires_blockers": bool(payload.get("blocked_requires_blockers", True)),
        "no_blocker_markers": no_blocker_markers,
    }


def blockers_present(
    blocker_lines: list[str] | None,
    no_blocker_markers: set[str] | None = None,
) -> bool:
    markers = {_normalize_policy_phrase(item) for item in (no_blocker_markers or set())}
    for item in _section_items(list(blocker_lines or [])):
        normalized = _normalize_policy_phrase(item)
        if not normalized:
            continue
        if normalized not in markers:
            return True
    return False


def evaluate_task_outcome_status_policy(
    task_outcome: dict[str, Any],
    *,
    blocker_lines: list[str] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_policy = policy or load_task_outcome_status_policy()
    decision_quality = str(task_outcome.get("decision_quality", "pending")).strip().lower() or "pending"
    declared_status = str(task_outcome.get("outcome_status", "in_progress")).strip().lower() or "in_progress"
    derived_status = active_policy["status_by_decision_quality"].get(decision_quality, declared_status)
    has_blockers = blockers_present(blocker_lines, active_policy["no_blocker_markers"])
    issues: list[str] = []
    if decision_quality not in ALLOWED_DECISION_QUALITY:
        issues.append(f"unsupported decision_quality for status policy: {decision_quality!r}")
    if (
        derived_status == "blocked"
        and active_policy["blocked_requires_blockers"]
        and not has_blockers
    ):
        issues.append(
            "decision_quality=environment_blocked requires an explicit unresolved blocker in ## Blockers"
        )
    return {
        "policy_path": active_policy["path"],
        "decision_quality": decision_quality,
        "declared_outcome_status": declared_status,
        "derived_outcome_status": derived_status,
        "blockers_present": has_blockers,
        "matches_declared_status": declared_status == derived_status,
        "issues": issues,
    }


def apply_task_outcome_status_policy(
    task_outcome: dict[str, Any],
    *,
    blocker_lines: list[str] | None = None,
    policy: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    evaluation = evaluate_task_outcome_status_policy(
        task_outcome,
        blocker_lines=blocker_lines,
        policy=policy,
    )
    canonical = dict(task_outcome)
    canonical["outcome_status"] = evaluation["derived_outcome_status"]
    return canonical, evaluation


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


def _git_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }


def get_repo_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError("not inside a git repository")
    return Path(completed.stdout.strip()).resolve()


def get_git_common_dir(repo_root: Path | None = None) -> Path:
    cwd = repo_root or Path.cwd()
    completed = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError("unable to resolve git common dir")
    raw = Path(completed.stdout.strip())
    if raw.is_absolute():
        return raw.resolve()
    return (cwd / raw).resolve()


def _run_git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        env=_git_env(),
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
        env=_git_env(),
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
        env=_git_env(),
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
    return _normalize_state_payload(state)


def save_state(path: Path, state: dict[str, Any]) -> None:
    write_json(path, _normalize_state_payload(state))


def _looks_like_filesystem_path(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(
        WINDOWS_ABS_PATH_RE.match(text)
        or text.startswith(("/", "\\"))
        or "/" in text
        or "\\" in text
    )


def _normalize_worktree_root(path_value: str | Path) -> Path:
    resolved = Path(path_value).resolve()
    if resolved.name.lower() == "agent-process" and resolved.parent.name.lower() == ".runlogs":
        return resolved.parent.parent
    if resolved.name.lower() == ".runlogs":
        return resolved.parent
    return resolved


def _normalize_worktree_path(path_value: str | Path) -> str:
    return _normalize_worktree_root(path_value).as_posix().lower()


def _scope_id_for_worktree(path_value: str | Path) -> str:
    return _normalize_worktree_path(path_value)


def _current_scope_id(repo_root: Path) -> str:
    return _scope_id_for_worktree(repo_root)


def _current_scope_key(state: dict[str, Any], repo_root: Path) -> str:
    scope_id = _current_scope_id(repo_root)
    tasks_by_scope = state.get("tasks_by_scope", {})
    if isinstance(tasks_by_scope, dict) and scope_id in tasks_by_scope:
        return scope_id
    return scope_id


def _derive_scope_id(scope_id_raw: str | None, worktree_path: str | Path | None) -> str:
    if worktree_path:
        return _scope_id_for_worktree(worktree_path)
    raw = str(scope_id_raw or "").strip()
    if not raw or raw.lower() == "default":
        return "default"
    if _looks_like_filesystem_path(raw):
        return _scope_id_for_worktree(raw)
    return raw


def _canonicalize_task_payload(
    task: dict[str, Any],
    *,
    fallback_worktree_path: str | Path | None = None,
) -> dict[str, Any]:
    clone = dict(task)
    worktree_path = str(clone.get("worktree_path", "")).strip()
    if worktree_path:
        clone["worktree_path"] = str(_normalize_worktree_root(worktree_path))
        worktree_path = str(clone["worktree_path"])
    elif fallback_worktree_path is not None:
        clone["worktree_path"] = str(_normalize_worktree_root(fallback_worktree_path))
        worktree_path = str(clone["worktree_path"])
    scope_id = _derive_scope_id(str(clone.get("scope_id", "")).strip(), worktree_path or None)
    clone["scope_id"] = scope_id
    return clone


def _normalize_state_payload(state: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(state or {})
    raw_tasks = normalized.get("tasks_by_scope")
    tasks_by_scope: dict[str, dict[str, Any]] = {}
    if isinstance(raw_tasks, dict):
        for scope_id, task in raw_tasks.items():
            if isinstance(task, dict):
                fallback_worktree = str(scope_id) if _looks_like_filesystem_path(str(scope_id)) else None
                clone = _canonicalize_task_payload(
                    task,
                    fallback_worktree_path=fallback_worktree,
                )
                _merge_task_snapshot(
                    tasks_by_scope,
                    incoming_task=clone,
                    fallback_mtime=0.0,
                )
    active = normalized.get("active_task")
    if isinstance(active, dict):
        clone = _canonicalize_task_payload(active)
        _merge_task_snapshot(
            tasks_by_scope,
            incoming_task=clone,
            fallback_mtime=0.0,
        )
        normalized["active_task"] = clone
    else:
        normalized["active_task"] = None
    normalized["version"] = max(int(normalized.get("version", 1) or 1), 2)
    normalized["tasks_by_scope"] = tasks_by_scope
    migration = normalized.get("migration", {})
    normalized["migration"] = migration if isinstance(migration, dict) else {}
    return normalized


def _event_identity(event: dict[str, Any]) -> tuple[str, str, str]:
    event_type = str(event.get("event_type", "")).strip()
    task_id = str(event.get("task_id", "")).strip()
    marker = ""
    for field in ("started_at", "timestamp", "closed_at"):
        marker = str(event.get(field, "")).strip()
        if marker:
            break
    if not marker:
        marker = json.dumps(event, ensure_ascii=False, sort_keys=True)
    return event_type, task_id, marker


def _event_sort_key(event: dict[str, Any]) -> tuple[datetime, str, str]:
    for field in ("started_at", "timestamp", "closed_at"):
        parsed = parse_iso_datetime(str(event.get(field, "")).strip())
        if parsed is not None:
            return parsed, str(event.get("task_id", "")), str(event.get("event_type", ""))
    return datetime.min.replace(tzinfo=timezone.utc), str(event.get("task_id", "")), str(event.get("event_type", ""))


def _load_events_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            items.append(payload)
    return items


def _write_events_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in sorted(events, key=_event_sort_key):
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _state_freshness(task: dict[str, Any], *, fallback_mtime: float) -> float:
    for field in ("closed_at", "first_patch_at", "started_at"):
        parsed = parse_iso_datetime(str(task.get(field, "")).strip())
        if parsed is not None:
            return parsed.timestamp()
    return fallback_mtime


def _merge_task_snapshot(
    tasks_by_scope: dict[str, dict[str, Any]],
    *,
    incoming_task: dict[str, Any],
    fallback_mtime: float,
    fallback_worktree_path: str | Path | None = None,
) -> None:
    task = _canonicalize_task_payload(
        incoming_task,
        fallback_worktree_path=fallback_worktree_path,
    )
    scope_id = str(task.get("scope_id", "")).strip() or "default"
    task["scope_id"] = scope_id
    existing = tasks_by_scope.get(scope_id)
    if existing is None:
        tasks_by_scope[scope_id] = task
        return
    if _state_freshness(task, fallback_mtime=fallback_mtime) >= _state_freshness(existing, fallback_mtime=fallback_mtime):
        tasks_by_scope[scope_id] = task


def list_git_worktrees(repo_root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    if completed.returncode != 0:
        return [repo_root]
    worktrees: list[Path] = []
    for raw in completed.stdout.splitlines():
        if not raw.startswith("worktree "):
            continue
        worktrees.append(Path(raw.replace("worktree ", "", 1).strip()).resolve())
    return worktrees or [repo_root]


def legacy_process_roots(repo_root: Path, canonical_root: Path) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    canonical = canonical_root.resolve()
    for worktree in list_git_worktrees(repo_root):
        candidate = (worktree / ".runlogs" / "agent-process").resolve()
        if candidate == canonical or not candidate.exists():
            continue
        key = candidate.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(candidate)
    return roots


def _worktree_for_process_root(process_root: Path, fallback_worktree: Path) -> Path:
    resolved = process_root.resolve()
    if resolved.name.lower() == "agent-process" and resolved.parent.name.lower() == ".runlogs":
        return resolved.parent.parent.resolve()
    return _normalize_worktree_root(fallback_worktree)


def reconcile_legacy_process_storage_with_summary(
    repo_root: Path,
    *,
    events_path: Path,
    state_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    canonical_root = state_path.parent.resolve()
    canonical_worktree = _worktree_for_process_root(canonical_root, repo_root)
    canonical_state = load_json(state_path, default={"version": 2})
    state = _normalize_state_payload(canonical_state)
    default_scope = state.get("tasks_by_scope", {}).get("default")
    canonical_scope_id = _scope_id_for_worktree(canonical_worktree)
    repaired_scope_count = 0
    if isinstance(default_scope, dict):
        state["tasks_by_scope"].pop("default", None)
        _merge_task_snapshot(
            state["tasks_by_scope"],
            incoming_task=default_scope,
            fallback_mtime=state_path.stat().st_mtime if state_path.exists() else 0.0,
            fallback_worktree_path=canonical_worktree,
        )
        repaired_scope_count += 1
    canonical_events = _load_events_jsonl(events_path)
    known_event_ids = {_event_identity(event) for event in canonical_events}
    imported_roots: list[str] = []
    imported_event_count = 0
    merged_scope_count = 0
    changed_events = False
    changed_state = False
    initial_state_signature = json.dumps(state, ensure_ascii=False, sort_keys=True)

    for legacy_root in legacy_process_roots(repo_root, canonical_root):
        imported_roots.append(str(legacy_root))
        legacy_worktree = _worktree_for_process_root(legacy_root, legacy_root.parent.parent)
        legacy_events_path = legacy_root / "task-events.jsonl"
        if legacy_events_path.exists():
            for event in _load_events_jsonl(legacy_events_path):
                identity = _event_identity(event)
                if identity in known_event_ids:
                    continue
                canonical_events.append(event)
                known_event_ids.add(identity)
                imported_event_count += 1
                changed_events = True

        legacy_state_path = legacy_root / "state.json"
        if legacy_state_path.exists():
            legacy_state = _normalize_state_payload(load_json(legacy_state_path, default={"version": 1}))
            fallback_mtime = legacy_state_path.stat().st_mtime
            for scope_id, task in legacy_state.get("tasks_by_scope", {}).items():
                incoming = dict(task)
                incoming.setdefault("scope_id", scope_id)
                incoming.setdefault("worktree_path", str(legacy_worktree))
                before_signature = json.dumps(state.get("tasks_by_scope", {}), ensure_ascii=False, sort_keys=True)
                _merge_task_snapshot(
                    state["tasks_by_scope"],
                    incoming_task=incoming,
                    fallback_mtime=fallback_mtime,
                    fallback_worktree_path=legacy_worktree,
                )
                after_signature = json.dumps(state.get("tasks_by_scope", {}), ensure_ascii=False, sort_keys=True)
                if after_signature != before_signature:
                    merged_scope_count += 1
                    changed_state = True

    summary = {
        "canonical_root": str(canonical_root),
        "canonical_worktree": str(canonical_worktree),
        "canonical_scope_id": canonical_scope_id,
        "legacy_roots_seen": sorted(imported_roots),
        "legacy_root_count": len(imported_roots),
        "imported_event_count": imported_event_count,
        "merged_scope_count": merged_scope_count,
        "repaired_scope_count": repaired_scope_count,
        "event_count": len(canonical_events),
        "tasks_by_scope_count": len(state.get("tasks_by_scope", {})),
        "last_reconciled_at": now_utc_iso(),
    }
    state["migration"]["canonical_root"] = summary["canonical_root"]
    state["migration"]["canonical_worktree"] = summary["canonical_worktree"]
    state["migration"]["canonical_scope_id"] = summary["canonical_scope_id"]
    state["migration"]["legacy_roots_seen"] = summary["legacy_roots_seen"]
    state["migration"]["last_reconciled_at"] = summary["last_reconciled_at"]
    state["migration"]["last_reconcile_summary"] = summary
    current = state["tasks_by_scope"].get(_current_scope_id(repo_root))
    state["active_task"] = dict(current) if isinstance(current, dict) else None
    final_state_signature = json.dumps(state, ensure_ascii=False, sort_keys=True)
    changed_state = changed_state or final_state_signature != initial_state_signature

    if changed_events:
        _write_events_jsonl(events_path, canonical_events)
    if changed_state:
        save_state(state_path, state)
        state = load_state(state_path)
    return state, summary


def reconcile_legacy_process_storage(repo_root: Path, *, events_path: Path, state_path: Path) -> dict[str, Any]:
    state, _ = reconcile_legacy_process_storage_with_summary(
        repo_root,
        events_path=events_path,
        state_path=state_path,
    )
    return state


def get_active_task(state: dict[str, Any], repo_root: Path) -> dict[str, Any] | None:
    normalized = _normalize_state_payload(state)
    scope_id = _current_scope_id(repo_root)
    task = normalized.get("tasks_by_scope", {}).get(scope_id)
    if isinstance(task, dict):
        return dict(task)
    if normalized.get("tasks_by_scope"):
        return None
    active = normalized.get("active_task")
    return dict(active) if isinstance(active, dict) else None


def set_active_task(state: dict[str, Any], repo_root: Path, task: dict[str, Any] | None) -> dict[str, Any]:
    normalized = _normalize_state_payload(state)
    scope_id = _current_scope_id(repo_root)
    if task is None:
        normalized.get("tasks_by_scope", {}).pop(scope_id, None)
        normalized["active_task"] = None
        return normalized
    clone = dict(task)
    clone["scope_id"] = scope_id
    clone["worktree_path"] = str(repo_root.resolve())
    normalized["tasks_by_scope"][scope_id] = clone
    normalized["active_task"] = clone
    return normalized


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
    start_recommendations: list[str],
    baseline_changed_files: list[str],
    baseline_diff_hash: str,
    worktree_path: Path,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "task_key": task_key,
        "scope_id": _scope_id_for_worktree(worktree_path),
        "worktree_path": str(worktree_path.resolve()),
        "started_at": now_utc_iso(),
        "branch": branch,
        "head_sha": head_sha,
        "start_primary_context": start_primary_context or "unknown",
        "start_contexts": list(start_contexts),
        "intent_sources": list(intent_sources),
        "unmapped_files_count": len(unmapped_files),
        "start_recommendations": list(start_recommendations),
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
    state = reconcile_legacy_process_storage(repo_root, events_path=events_path, state_path=state_path)
    handoff = parse_session_handoff(handoff_path)
    branch = get_current_branch(repo_root)
    task_key = build_task_key(branch, handoff)
    active = get_active_task(state, repo_root)
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
        start_recommendations=list(route.get("recommendations", [])),
        baseline_changed_files=changed_files,
        baseline_diff_hash=baseline_diff_hash,
        worktree_path=repo_root,
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
            "start_recommendations": active_task["start_recommendations"],
            "scope_id": active_task["scope_id"],
            "worktree_path": active_task["worktree_path"],
        },
    )
    state = set_active_task(state, repo_root, active_task)
    save_state(state_path, state)
    return True, active_task


def record_first_patch(*, events_path: Path, state_path: Path, handoff_path: Path) -> tuple[bool, dict[str, Any] | None]:
    repo_root = get_repo_root()
    state = reconcile_legacy_process_storage(repo_root, events_path=events_path, state_path=state_path)
    active = get_active_task(state, repo_root)
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
                "scope_id": active["scope_id"],
                "worktree_path": active["worktree_path"],
            },
        )
        state = set_active_task(state, repo_root, active)
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
    state = set_active_task(state, repo_root, active)
    save_state(state_path, state)
    return False, active


def record_task_end(
    *,
    events_path: Path,
    state_path: Path,
    handoff_path: Path,
    task_outcome: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    repo_root = get_repo_root()
    state = reconcile_legacy_process_storage(repo_root, events_path=events_path, state_path=state_path)
    active = get_active_task(state, repo_root)
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
            "scope_id": active["scope_id"],
            "worktree_path": active["worktree_path"],
        },
    )
    state = set_active_task(state, repo_root, active)
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
        "start_recommendations": list(active_task.get("start_recommendations", [])),
    }


def _normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    start_recommendations = raw.get("start_recommendations", [])
    if not isinstance(start_recommendations, list):
        start_recommendations = []
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
        "start_recommendations": [str(item).strip() for item in start_recommendations if str(item).strip()],
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
    from moex_carry.governance.process_reports import compute_process_rollup as _compute_process_rollup

    return _compute_process_rollup(payload, window_size=window_size)


def render_rollup_markdown(rollup: dict[str, Any]) -> str:
    from moex_carry.governance.process_reports import render_rollup_markdown as _render_rollup_markdown

    return _render_rollup_markdown(rollup)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record and roll up agent process telemetry.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("start", "first-patch", "end"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--events-path", default=str(default_events_path()))
        sub.add_argument("--state-path", default=str(default_state_path()))
        sub.add_argument("--session-handoff-path", default=str(default_session_handoff_path()))

    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("--events-path", default=str(default_events_path()))
    reconcile.add_argument("--state-path", default=str(default_state_path()))

    rollup = subparsers.add_parser("rollup")
    rollup.add_argument("--task-outcomes-path", default=str(default_task_outcomes_path()))
    rollup.add_argument("--window-size", type=int, default=ROLLING_WINDOW_SIZE)
    rollup.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "start":
        state_path = Path(args.state_path)
        created, active = start_task(
            events_path=Path(args.events_path),
            state_path=state_path,
            handoff_path=Path(args.session_handoff_path),
        )
        if active is None:
            print("agent process telemetry: skipped (no active task)")
            return 0
        verb = "started" if created else "unchanged"
        print(
            "agent process telemetry: "
            f"{verb} task_id={active['task_id']} context={active['start_primary_context']} "
            f"root={state_path.parent.resolve()} worktree={active['worktree_path']}"
        )
        return 0

    if args.command == "first-patch":
        state_path = Path(args.state_path)
        recorded, active = record_first_patch(
            events_path=Path(args.events_path),
            state_path=state_path,
            handoff_path=Path(args.session_handoff_path),
        )
        if active is None:
            print("agent process telemetry: no active task")
            return 0
        if recorded:
            print(
                "agent process telemetry: "
                f"first_patch task_id={active['task_id']} "
                f"time_to_first_patch_sec={active['time_to_first_patch_sec']} "
                f"root={state_path.parent.resolve()} worktree={active['worktree_path']}"
            )
        else:
            print("agent process telemetry: first_patch no-op")
        return 0

    if args.command == "end":
        state_path = Path(args.state_path)
        handoff = parse_session_handoff(Path(args.session_handoff_path))
        task_outcome, policy_evaluation = apply_task_outcome_status_policy(
            normalize_task_outcome(handoff.get("task_outcome", {})),
            blocker_lines=handoff.get("blockers_lines", []),
        )
        if policy_evaluation["issues"]:
            print("agent process telemetry: end blocked by task outcome policy")
            for issue in policy_evaluation["issues"]:
                print(f"  {issue}")
            print(f"  policy={policy_evaluation['policy_path']}")
            return 1
        recorded, active = record_task_end(
            events_path=Path(args.events_path),
            state_path=state_path,
            handoff_path=Path(args.session_handoff_path),
            task_outcome=task_outcome,
        )
        if active is None:
            print("agent process telemetry: no active task")
            return 0
        if recorded:
            print(
                "agent process telemetry: "
                f"ended task_id={active['task_id']} outcome={active['outcome_status']} "
                f"root={state_path.parent.resolve()} worktree={active['worktree_path']}"
            )
            if not policy_evaluation["matches_declared_status"]:
                print(
                    "  status_policy_override: "
                    f"{policy_evaluation['declared_outcome_status']} -> "
                    f"{policy_evaluation['derived_outcome_status']}"
                )
        else:
            print("agent process telemetry: end no-op")
        return 0

    if args.command == "reconcile":
        state, summary = reconcile_legacy_process_storage_with_summary(
            get_repo_root(),
            events_path=Path(args.events_path),
            state_path=Path(args.state_path),
        )
        active = state.get("active_task")
        active_task_id = active.get("task_id") if isinstance(active, dict) else "none"
        print(
            "agent process telemetry: "
            f"reconciled root={summary['canonical_root']} "
            f"worktree={summary['canonical_worktree']} active_task_id={active_task_id} "
            f"legacy_roots={summary['legacy_root_count']} imported_events={summary['imported_event_count']} "
            f"merged_scopes={summary['merged_scope_count']} repaired_scopes={summary['repaired_scope_count']} "
            f"tasks_by_scope={summary['tasks_by_scope_count']} events={summary['event_count']}"
        )
        for root in summary["legacy_roots_seen"]:
            print(f"  legacy_root={root}")
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
