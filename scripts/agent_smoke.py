from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_PROFILES = ("core", "ui", "news", "full")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    parser = argparse.ArgumentParser(description="Smoke-check runtime harness coordinates.")
    parser.add_argument("--profile", choices=ALLOWED_PROFILES, default="core")
    args = parser.parse_args()

    task_id = _active_task_id()
    runtime_dir = Path(".runlogs/runtime") / task_id
    coordinates_path = runtime_dir / "coordinates.json"
    metrics_path = runtime_dir / "metrics.json"
    if not coordinates_path.exists():
        print("agent_smoke: missing runtime coordinates. Run agent_bootstrap first.")
        return 1

    coordinates = json.loads(coordinates_path.read_text(encoding="utf-8"))
    if str(coordinates.get("profile")) != args.profile:
        print(
            "agent_smoke: profile mismatch "
            f"(expected={args.profile} got={coordinates.get('profile')})"
        )
        return 1
    if not Path(str(coordinates.get("logs_path"))).exists():
        print("agent_smoke: logs path from coordinates is missing.")
        return 1

    metrics = {"generated_at_utc": _utc_now(), "profile": args.profile, "status": "smoke_ok"}
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("agent_smoke: OK")
    print(json.dumps({"task_id": task_id, "profile": args.profile, "metrics_path": str(metrics_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
