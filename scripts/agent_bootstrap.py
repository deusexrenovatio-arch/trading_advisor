from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_PROFILES = ("core", "ui", "news", "full")
DEFAULT_SERVER_PORT = 8050
DEFAULT_STARTUP_TIMEOUT_SEC = 45
DEFAULT_SHUTDOWN_TIMEOUT_SEC = 15


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _load_active_task_id() -> str:
    state_path = Path(".runlogs/agent-process/state.json")
    if not state_path.exists():
        return "no-task"
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return "no-task"
    active = payload.get("active_task") if isinstance(payload, dict) else None
    if not isinstance(active, dict):
        return "no-task"
    return str(active.get("task_id") or "no-task")


def _default_server_command() -> list[str]:
    return [sys.executable, "scripts/run_server.py", "--config", "configs/default.yaml"]


def _runtime_targets_for_profile(profile: str) -> list[dict[str, object]]:
    base_command = _default_server_command()
    port_probe = {
        "type": "port",
        "host": "127.0.0.1",
        "port": DEFAULT_SERVER_PORT,
    }
    core_probe = {
        "type": "http",
        "url": f"http://127.0.0.1:{DEFAULT_SERVER_PORT}/api/v2/ops/health",
        "ok_status": [200, 503],
    }
    ui_probe = {
        "type": "http",
        "url": f"http://127.0.0.1:{DEFAULT_SERVER_PORT}/decision-audit",
        "ok_status": [200, 503],
    }
    news_probe = {
        "type": "http",
        "url": f"http://127.0.0.1:{DEFAULT_SERVER_PORT}/api/v2/news/feed",
        "ok_status": [200, 503],
    }
    if profile == "core":
        probes = [port_probe, core_probe]
    elif profile == "ui":
        probes = [port_probe, ui_probe]
    elif profile == "news":
        probes = [port_probe, news_probe]
    else:
        probes = [port_probe, core_probe, ui_probe, news_probe]

    return [
        {
            "id": f"{profile}-runtime",
            "command": base_command,
            "startup_timeout_sec": DEFAULT_STARTUP_TIMEOUT_SEC,
            "shutdown_timeout_sec": DEFAULT_SHUTDOWN_TIMEOUT_SEC,
            "probes": probes,
        }
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap runtime coordinates for the active task.")
    parser.add_argument("--profile", choices=ALLOWED_PROFILES, default="core")
    args = parser.parse_args()

    task_id = _load_active_task_id()
    runtime_dir = Path(".runlogs/runtime") / task_id
    runtime_dir.mkdir(parents=True, exist_ok=True)

    coordinates = {
        "version": 2,
        "generated_at_utc": _utc_now(),
        "task_id": task_id,
        "profile": args.profile,
        "worktree": str(Path.cwd().resolve()),
        "branch": _git_branch(),
        "logs_path": str((runtime_dir / "runtime.log").as_posix()),
        "metrics_path": str((runtime_dir / "metrics.json").as_posix()),
        "runtime_targets": _runtime_targets_for_profile(args.profile),
    }
    (runtime_dir / "runtime.log").touch()
    (runtime_dir / "metrics.json").write_text(
        json.dumps(
            {
                "generated_at_utc": _utc_now(),
                "profile": args.profile,
                "status": "bootstrapped",
                "runtime_targets": [target["id"] for target in coordinates["runtime_targets"]],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    coordinates_path = runtime_dir / "coordinates.json"
    coordinates_path.write_text(json.dumps(coordinates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(coordinates, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
