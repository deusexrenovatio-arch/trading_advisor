from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_CONTEXT_FILE = Path(".worktree-context.local.json")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return Path.cwd().resolve()
    return Path(completed.stdout.strip()).resolve()


def _git_branch() -> str:
    completed = subprocess.run(
        ["git", "branch", "--show-current"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return "<unknown>"
    value = completed.stdout.strip()
    return value or "<detached>"


def _load_context(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _write_context(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _delegate_to_powershell(args: argparse.Namespace) -> int:
    command = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts/worktree_guard.ps1",
        "-Action",
        args.action,
    ]
    if args.action.lower() == "init":
        if args.worktree_path:
            command.extend(["-WorktreePath", args.worktree_path])
        if args.branch:
            command.extend(["-Branch", args.branch])
        command.extend(["-ContextTtlHours", str(args.context_ttl_hours)])
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


def _python_init(args: argparse.Namespace, context_file: Path) -> int:
    worktree = Path(args.worktree_path or _git_root()).resolve()
    branch = args.branch or _git_branch()
    payload = {
        "expected_worktree": str(worktree),
        "expected_branch": branch,
        "valid_until": _iso(_now() + timedelta(hours=int(args.context_ttl_hours))),
        "ttl_hours": int(args.context_ttl_hours),
    }
    _write_context(context_file, payload)
    print("worktree_guard(py): initialized")
    print(f"  context_file: {context_file.as_posix()}")
    print(f"  expected_worktree: {payload['expected_worktree']}")
    print(f"  expected_branch: {payload['expected_branch']}")
    print(f"  ttl_hours: {payload['ttl_hours']}")
    return 0


def _python_show(context_file: Path) -> int:
    payload = _load_context(context_file)
    if not payload:
        print("worktree_guard(py): context is not set")
        return 1
    print("worktree_guard(py): status")
    print(f"  context_file: {context_file.as_posix()}")
    print(f"  expected_worktree: {payload.get('expected_worktree')}")
    print(f"  expected_branch: {payload.get('expected_branch')}")
    print(f"  valid_until: {payload.get('valid_until')}")
    return 0


def _python_clear(context_file: Path) -> int:
    if context_file.exists():
        context_file.unlink()
        print(f"worktree_guard(py): cleared context file {context_file.as_posix()}")
    else:
        print(f"worktree_guard(py): context file not found ({context_file.as_posix()})")
    return 0


def _python_check(context_file: Path) -> int:
    payload = _load_context(context_file)
    if not payload:
        print("worktree_guard(py): context is not set. Run init first.")
        return 1
    expected_worktree = str(payload.get("expected_worktree", "")).strip()
    expected_branch = str(payload.get("expected_branch", "")).strip()
    valid_until = str(payload.get("valid_until", "")).strip()

    current_worktree = str(_git_root())
    current_branch = _git_branch()

    try:
        valid_until_dt = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
    except Exception:
        print("worktree_guard(py): invalid context expiration timestamp")
        return 1
    if _now() > valid_until_dt:
        print(f"worktree_guard(py): context expired at {valid_until}")
        return 1
    if current_worktree != expected_worktree or current_branch != expected_branch:
        print("worktree_guard(py): mismatch detected")
        print(f"  current_worktree: {current_worktree}")
        print(f"  expected_worktree: {expected_worktree}")
        print(f"  current_branch: {current_branch}")
        print(f"  expected_branch: {expected_branch}")
        return 1

    print("worktree_guard(py): OK")
    print(f"  worktree: {current_worktree}")
    print(f"  branch: {current_branch}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-platform worktree guard entrypoint.")
    parser.add_argument("--action", required=True, choices=("Init", "Check", "Show", "Clear"))
    parser.add_argument("--worktree-path", default=None)
    parser.add_argument("--branch", default=None)
    parser.add_argument("--context-ttl-hours", type=int, default=12)
    parser.add_argument("--context-file", default=str(DEFAULT_CONTEXT_FILE))
    parser.add_argument(
        "--force-python",
        action="store_true",
        help="Run Python implementation even on Windows.",
    )
    args = parser.parse_args()
    context_file = Path(args.context_file)

    if os.name == "nt" and not args.force_python:
        return _delegate_to_powershell(args)

    action = args.action.lower()
    if action == "init":
        return _python_init(args, context_file)
    if action == "check":
        return _python_check(context_file)
    if action == "show":
        return _python_show(context_file)
    if action == "clear":
        return _python_clear(context_file)
    print(f"unsupported action: {args.action}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
