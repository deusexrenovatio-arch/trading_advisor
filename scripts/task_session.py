from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_SESSION_LOCK = Path(".runlogs/task-session/session-lock.json")
DEFAULT_SESSION_TTL_HOURS = 12


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


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


def get_current_branch(repo_root: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return "<unknown>"
    value = completed.stdout.strip()
    return value or "<detached>"


def default_session_lock_path(repo_root: Path | None = None) -> Path:
    root = repo_root or get_repo_root()
    return (root / DEFAULT_SESSION_LOCK).resolve()


def load_session_lock(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_session_lock(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clear_session_lock(path: Path) -> None:
    if path.exists():
        path.unlink()


def build_session_id() -> str:
    return f"TS-{_now().strftime('%Y%m%dT%H%M%SZ')}-{os.urandom(4).hex()}"


def create_session_lock(
    *,
    repo_root: Path,
    ttl_hours: int,
) -> dict[str, Any]:
    started_at = _now()
    return {
        "session_id": build_session_id(),
        "worktree": str(repo_root),
        "branch": get_current_branch(repo_root),
        "started_at": _iso(started_at),
        "expires_at": _iso(started_at + timedelta(hours=max(ttl_hours, 1))),
    }


def evaluate_session_lock(
    payload: dict[str, Any],
    *,
    repo_root: Path,
) -> tuple[bool, str]:
    if not payload:
        return False, "session lock is not set"
    worktree = str(payload.get("worktree", "")).strip()
    branch = str(payload.get("branch", "")).strip()
    started_at = _parse_iso(str(payload.get("started_at", "")).strip())
    expires_at = _parse_iso(str(payload.get("expires_at", "")).strip())
    session_id = str(payload.get("session_id", "")).strip()
    if not all((worktree, branch, started_at, expires_at, session_id)):
        return False, "session lock is invalid"
    current_branch = get_current_branch(repo_root)
    current_worktree = str(repo_root)
    if os.name == "nt":
        same_worktree = current_worktree.casefold() == worktree.casefold()
    else:
        same_worktree = current_worktree == worktree
    if not same_worktree or current_branch != branch:
        return False, (
            "session mismatch "
            f"(expected worktree={worktree} branch={branch}, current worktree={current_worktree} branch={current_branch})"
        )
    if _now() > expires_at:
        return False, f"session expired at {payload['expires_at']}"
    return True, "ok"


def require_active_session(*, lock_path: Path | None = None, quiet: bool = False) -> int:
    code, message, payload = check_active_session(lock_path=lock_path)
    if code != 0:
        if not quiet:
            print(f"task session: inactive ({message})")
            print(
                "task session: run `python scripts/task_session.py begin --request \"<request>\"` first"
            )
        return code
    if not quiet:
        print(
            "task session: OK "
            f"(session_id={payload['session_id']} branch={payload['branch']} worktree={payload['worktree']})"
        )
    return 0


def check_active_session(
    *,
    lock_path: Path | None = None,
) -> tuple[int, str, dict[str, Any]]:
    repo_root = get_repo_root()
    session_lock_path = lock_path or default_session_lock_path(repo_root)
    payload = load_session_lock(session_lock_path)
    ok, message = evaluate_session_lock(payload, repo_root=repo_root)
    if not ok:
        return 1, message, payload
    return 0, "ok", payload


def _session_handoff_text(path: Path) -> str:
    try:
        from handoff_resolver import read_task_note_lines
    except Exception:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
    if not path.exists():
        return ""
    _resolved_path, lines, _is_pointer = read_task_note_lines(path)
    return "\n".join(lines)


def _route_begin_context(*, request: str, handoff_path: Path) -> dict[str, Any]:
    from context_router import route_files

    return route_files(
        [],
        request_text=request,
        target_modules=[],
        session_handoff_text=_session_handoff_text(handoff_path),
    )


def _active_task_summary(*, repo_root: Path, state_path: Path) -> dict[str, Any] | None:
    try:
        from agent_process_telemetry import get_active_task, load_state
    except Exception:
        return None
    state = load_state(state_path)
    active = get_active_task(state, repo_root)
    return active if isinstance(active, dict) else None


def begin_session(
    *,
    request: str,
    ttl_hours: int,
    session_handoff_path: Path,
    events_path: Path,
    state_path: Path,
    lock_path: Path | None = None,
) -> int:
    if not request.strip():
        print("task session: begin requires non-empty --request")
        return 2

    repo_root = get_repo_root()
    session_lock_path = lock_path or default_session_lock_path(repo_root)
    existing = load_session_lock(session_lock_path)
    ok, message = evaluate_session_lock(existing, repo_root=repo_root)
    if ok:
        print(
            "task session: already active "
            f"(session_id={existing['session_id']} branch={existing['branch']})"
        )
        print("task session: end the current session before starting a new one")
        return 1

    route = _route_begin_context(request=request.strip(), handoff_path=session_handoff_path)
    payload = create_session_lock(repo_root=repo_root, ttl_hours=ttl_hours)
    write_session_lock(session_lock_path, payload)

    from agent_process_telemetry import start_task

    created, active = start_task(
        events_path=events_path,
        state_path=state_path,
        handoff_path=session_handoff_path,
        route_override={
            "primary_context": route.get("primary_context"),
            "contexts": [
                entry["id"]
                for entry in route.get("contexts", [])
                if isinstance(entry, dict) and str(entry.get("id", "")).strip()
            ],
            "intent_sources": list(route.get("intent_sources", [])),
            "unmapped_files": list(route.get("unmapped_files", [])),
            "recommendations": list(route.get("recommendations", [])),
        },
        baseline_changed_files_override=[],
    )
    if not created and not isinstance(active, dict):
        clear_session_lock(session_lock_path)
        print("task session: failed to create active task telemetry state")
        return 1

    active = _active_task_summary(repo_root=repo_root, state_path=state_path) or active
    task_id = str(active.get("task_id", "<unknown>")) if isinstance(active, dict) else "<unknown>"
    primary_context = route.get("primary_context") or "unknown"
    print("task session: started")
    print(f"  session_id: {payload['session_id']}")
    print(f"  task_id: {task_id}")
    print(f"  primary_context: {primary_context}")
    print("  next_gate: python scripts/run_loop_gate.py --from-git --git-ref HEAD")
    recommendations = [
        str(item).strip()
        for item in route.get("recommendations", [])
        if str(item).strip()
    ]
    for note in recommendations[:3]:
        print(f"  note: {note}")
    return 0


def session_status(
    *,
    state_path: Path,
    lock_path: Path | None = None,
    quiet: bool = False,
) -> int:
    repo_root = get_repo_root()
    session_lock_path = lock_path or default_session_lock_path(repo_root)
    payload = load_session_lock(session_lock_path)
    ok, message = evaluate_session_lock(payload, repo_root=repo_root)
    if not ok:
        if not quiet:
            print(f"task session: inactive ({message})")
        return 1
    if quiet:
        return 0

    print("task session: active")
    print(f"  session_id: {payload['session_id']}")
    print(f"  worktree: {payload['worktree']}")
    print(f"  branch: {payload['branch']}")
    print(f"  started_at: {payload['started_at']}")
    print(f"  expires_at: {payload['expires_at']}")
    active = _active_task_summary(repo_root=repo_root, state_path=state_path)
    if isinstance(active, dict):
        print(f"  task_id: {active.get('task_id')}")
        print(f"  start_primary_context: {active.get('start_primary_context')}")
    return 0


def end_session(
    *,
    session_handoff_path: Path,
    events_path: Path,
    state_path: Path,
    task_outcomes_path: Path,
    lock_path: Path | None = None,
) -> int:
    repo_root = get_repo_root()
    session_lock_path = lock_path or default_session_lock_path(repo_root)
    payload = load_session_lock(session_lock_path)
    ok, message = evaluate_session_lock(payload, repo_root=repo_root)
    if not ok:
        print(f"task session: cannot end inactive session ({message})")
        return 1

    from agent_process_telemetry import (
        apply_task_outcome_status_policy,
        normalize_task_outcome,
        parse_session_handoff,
        record_task_end,
    )
    import sync_task_outcomes

    handoff = parse_session_handoff(session_handoff_path)
    task_outcome, policy_evaluation = apply_task_outcome_status_policy(
        normalize_task_outcome(handoff.get("task_outcome", {})),
        blocker_lines=handoff.get("blockers_lines", []),
    )
    if task_outcome["outcome_status"] == "in_progress":
        print("task session: end requires terminal Task Outcome status")
        return 1
    if policy_evaluation["issues"]:
        print("task session: end blocked by task outcome policy")
        for issue in policy_evaluation["issues"]:
            print(f"  {issue}")
        return 1

    recorded, active = record_task_end(
        events_path=events_path,
        state_path=state_path,
        handoff_path=session_handoff_path,
        task_outcome=task_outcome,
    )
    if active is None:
        print("task session: no active telemetry task to end")
        return 1
    sync_rc = sync_task_outcomes.run(
        session_handoff_path=session_handoff_path,
        state_path=state_path,
        events_path=events_path,
        task_outcomes_path=task_outcomes_path,
    )
    if sync_rc != 0:
        return sync_rc

    clear_session_lock(session_lock_path)
    print("task session: ended")
    print(f"  session_id: {payload['session_id']}")
    print(f"  task_id: {active.get('task_id')}")
    print(f"  outcome_status: {active.get('outcome_status')}")
    if not recorded:
        print("  note: telemetry end was already recorded")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Canonical task session lifecycle entrypoint.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    begin = subparsers.add_parser("begin")
    begin.add_argument("--request", required=True)
    begin.add_argument("--ttl-hours", type=int, default=DEFAULT_SESSION_TTL_HOURS)
    begin.add_argument("--session-handoff-path", default="docs/session_handoff.md")
    begin.add_argument("--events-path", default=None)
    begin.add_argument("--state-path", default=None)
    begin.add_argument("--lock-path", default=None)

    status = subparsers.add_parser("status")
    status.add_argument("--state-path", default=None)
    status.add_argument("--lock-path", default=None)
    status.add_argument("--quiet", action="store_true")

    end = subparsers.add_parser("end")
    end.add_argument("--session-handoff-path", default="docs/session_handoff.md")
    end.add_argument("--events-path", default=None)
    end.add_argument("--state-path", default=None)
    end.add_argument("--task-outcomes-path", default="memory/task_outcomes.yaml")
    end.add_argument("--lock-path", default=None)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    repo_root = get_repo_root()
    default_events = (repo_root / ".runlogs" / "agent-process" / "task-events.jsonl").resolve()
    default_state = (repo_root / ".runlogs" / "agent-process" / "state.json").resolve()

    if args.command == "begin":
        return begin_session(
            request=args.request,
            ttl_hours=args.ttl_hours,
            session_handoff_path=Path(args.session_handoff_path),
            events_path=Path(args.events_path) if args.events_path else default_events,
            state_path=Path(args.state_path) if args.state_path else default_state,
            lock_path=Path(args.lock_path) if args.lock_path else None,
        )
    if args.command == "status":
        return session_status(
            state_path=Path(args.state_path) if args.state_path else default_state,
            lock_path=Path(args.lock_path) if args.lock_path else None,
            quiet=bool(args.quiet),
        )
    if args.command == "end":
        return end_session(
            session_handoff_path=Path(args.session_handoff_path),
            events_path=Path(args.events_path) if args.events_path else default_events,
            state_path=Path(args.state_path) if args.state_path else default_state,
            task_outcomes_path=Path(args.task_outcomes_path),
            lock_path=Path(args.lock_path) if args.lock_path else None,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
