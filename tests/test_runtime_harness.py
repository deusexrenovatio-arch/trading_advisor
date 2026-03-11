from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)


def _reserve_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_active_task_state(repo_root: Path, task_id: str) -> None:
    state_path = repo_root / ".runlogs" / "agent-process" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"version": 1, "active_task": {"task_id": task_id}}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_agent_bootstrap_writes_profile_runtime_targets(tmp_path: Path) -> None:
    task_id = "TASK-BOOTSTRAP"
    _write_active_task_state(tmp_path, task_id)

    result = _run(
        [sys.executable, str(ROOT / "scripts/agent_bootstrap.py"), "--profile", "core"],
        tmp_path,
    )
    assert result.returncode == 0

    coordinates_path = tmp_path / ".runlogs/runtime" / task_id / "coordinates.json"
    payload = json.loads(coordinates_path.read_text(encoding="utf-8"))
    assert payload["profile"] == "core"
    assert isinstance(payload.get("runtime_targets"), list)
    assert payload["runtime_targets"]
    assert payload["runtime_targets"][0]["command"]
    assert payload["runtime_targets"][0]["probes"]


def test_agent_smoke_runs_process_and_checks_readiness(tmp_path: Path) -> None:
    task_id = "TASK-SMOKE"
    _write_active_task_state(tmp_path, task_id)
    runtime_dir = tmp_path / ".runlogs/runtime" / task_id
    runtime_dir.mkdir(parents=True, exist_ok=True)
    port = _reserve_free_port()

    coordinates = {
        "profile": "core",
        "logs_path": str((runtime_dir / "runtime.log").as_posix()),
        "metrics_path": str((runtime_dir / "metrics.json").as_posix()),
        "runtime_targets": [
            {
                "id": "dummy-http",
                "command": [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                "startup_timeout_sec": 20,
                "shutdown_timeout_sec": 5,
                "probes": [
                    {"type": "port", "host": "127.0.0.1", "port": port},
                    {"type": "http", "url": f"http://127.0.0.1:{port}/", "ok_status": [200]},
                ],
            }
        ],
    }
    (runtime_dir / "coordinates.json").write_text(
        json.dumps(coordinates, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (runtime_dir / "runtime.log").touch()

    result = _run(
        [sys.executable, str(ROOT / "scripts/agent_smoke.py"), "--profile", "core"],
        tmp_path,
    )
    assert result.returncode == 0

    metrics = json.loads((runtime_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["status"] == "smoke_ok"
    assert metrics["targets"][0]["status"] == "ok"
