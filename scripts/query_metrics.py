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
    parser = argparse.ArgumentParser(description="Query compact runtime metrics.")
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--key", default=None)
    args = parser.parse_args()

    task_id = args.task_id or _active_task_id()
    metrics_path = Path(".runlogs/runtime") / task_id / "metrics.json"
    if not metrics_path.exists():
        print(f"query_metrics: no metrics file for task_id={task_id}")
        return 1

    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    if args.key:
        print(json.dumps({args.key: payload.get(args.key)}, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
