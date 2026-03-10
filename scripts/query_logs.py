from __future__ import annotations

import argparse
import json
from pathlib import Path


def _active_task_id() -> str:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Query compact runtime log output.")
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--tail", type=int, default=50)
    args = parser.parse_args()

    task_id = args.task_id or _active_task_id()
    log_path = Path(".runlogs/runtime") / task_id / "runtime.log"
    if not log_path.exists():
        print(f"query_logs: no log file for task_id={task_id}")
        return 1

    lines = log_path.read_text(encoding="utf-8").splitlines()
    tail = max(int(args.tail), 1)
    for line in lines[-tail:]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
