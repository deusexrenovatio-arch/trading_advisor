from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request


ALLOWED_PROFILES = ("core", "ui", "news", "full")
DEFAULT_PROBE_TIMEOUT_SEC = 2.0
DEFAULT_STARTUP_TIMEOUT_SEC = 30
DEFAULT_SHUTDOWN_TIMEOUT_SEC = 10


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


def _port_probe_ok(host: str, port: int, *, timeout_sec: float) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_sec):
            return True
    except OSError:
        return False


def _http_probe_ok(url: str, *, ok_status: list[int], timeout_sec: float) -> bool:
    request = urllib_request.Request(url=url, method="GET")
    try:
        with urllib_request.urlopen(request, timeout=timeout_sec) as response:
            status_code = int(getattr(response, "status", 0) or 0)
    except urllib_error.HTTPError as exc:
        status_code = int(exc.code)
    except Exception:
        return False
    return status_code in ok_status


def _probe_ready(probes: list[dict[str, object]], *, startup_timeout_sec: int) -> bool:
    deadline = time.monotonic() + float(max(startup_timeout_sec, 1))
    while time.monotonic() <= deadline:
        all_ok = True
        for probe in probes:
            probe_type = str(probe.get("type") or "").strip().lower()
            if probe_type == "port":
                host = str(probe.get("host") or "127.0.0.1").strip() or "127.0.0.1"
                port = int(probe.get("port") or 0)
                ok = port > 0 and _port_probe_ok(host, port, timeout_sec=DEFAULT_PROBE_TIMEOUT_SEC)
            elif probe_type == "http":
                url = str(probe.get("url") or "").strip()
                ok_status_raw = probe.get("ok_status")
                if isinstance(ok_status_raw, list) and ok_status_raw:
                    ok_status = [int(value) for value in ok_status_raw]
                else:
                    ok_status = [200]
                ok = bool(url) and _http_probe_ok(url, ok_status=ok_status, timeout_sec=DEFAULT_PROBE_TIMEOUT_SEC)
            else:
                ok = False
            if not ok:
                all_ok = False
                break
        if all_ok:
            return True
        time.sleep(0.5)
    return False


def _terminate_process(process: subprocess.Popen[str], *, shutdown_timeout_sec: int) -> int | None:
    if process.poll() is not None:
        return process.returncode
    process.terminate()
    try:
        process.wait(timeout=max(int(shutdown_timeout_sec), 1))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    return process.returncode


def _run_target(target: dict[str, object], *, log_path: Path) -> dict[str, object]:
    target_id = str(target.get("id") or "runtime-target").strip() or "runtime-target"
    command = target.get("command")
    if not isinstance(command, list) or not all(str(part).strip() for part in command):
        return {
            "id": target_id,
            "status": "failed",
            "reason": "invalid_command",
        }
    probes_raw = target.get("probes")
    probes = [probe for probe in probes_raw if isinstance(probe, dict)] if isinstance(probes_raw, list) else []
    if not probes:
        return {
            "id": target_id,
            "status": "failed",
            "reason": "missing_probes",
        }
    startup_timeout_sec = int(target.get("startup_timeout_sec") or DEFAULT_STARTUP_TIMEOUT_SEC)
    shutdown_timeout_sec = int(target.get("shutdown_timeout_sec") or DEFAULT_SHUTDOWN_TIMEOUT_SEC)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = _utc_now()
    with log_path.open("a", encoding="utf-8") as log_handle:
        log_handle.write(f"[agent_smoke] target={target_id} started_at={started_at}\n")
        log_handle.flush()
        try:
            process = subprocess.Popen(
                [str(part) for part in command],
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as exc:
            log_handle.write(f"[agent_smoke] target={target_id} spawn_error={exc}\n")
            return {
                "id": target_id,
                "status": "failed",
                "reason": "spawn_error",
                "error": str(exc),
            }

        ready = _probe_ready(probes, startup_timeout_sec=startup_timeout_sec)
        exit_code = _terminate_process(process, shutdown_timeout_sec=shutdown_timeout_sec)
        finished_at = _utc_now()
        if not ready:
            log_handle.write(
                f"[agent_smoke] target={target_id} readiness_failed exit_code={exit_code}\n"
            )
            log_handle.flush()
            return {
                "id": target_id,
                "status": "failed",
                "reason": "readiness_failed",
                "exit_code": exit_code,
                "started_at": started_at,
                "finished_at": finished_at,
            }
        log_handle.write(f"[agent_smoke] target={target_id} readiness_ok exit_code={exit_code}\n")
        log_handle.flush()
    return {
        "id": target_id,
        "status": "ok",
        "exit_code": exit_code,
        "started_at": started_at,
        "finished_at": finished_at,
    }


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

    log_path = Path(str(coordinates.get("logs_path") or ""))
    metrics_path = Path(str(coordinates.get("metrics_path") or metrics_path))
    if not str(log_path).strip():
        print("agent_smoke: logs path from coordinates is missing.")
        return 1
    runtime_targets = coordinates.get("runtime_targets")
    if not isinstance(runtime_targets, list) or not runtime_targets:
        print("agent_smoke: runtime targets are missing. Re-run agent_bootstrap.")
        return 1

    results = [
        _run_target(target, log_path=log_path)
        for target in runtime_targets
        if isinstance(target, dict)
    ]
    all_ok = all(str(result.get("status")) == "ok" for result in results)

    metrics = {
        "generated_at_utc": _utc_now(),
        "profile": args.profile,
        "status": "smoke_ok" if all_ok else "smoke_failed",
        "targets": results,
    }
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not all_ok:
        print("agent_smoke: FAILED")
        print(
            json.dumps(
                {"task_id": task_id, "profile": args.profile, "metrics_path": str(metrics_path), "targets": results},
                indent=2,
            )
        )
        return 1

    print("agent_smoke: OK")
    print(
        json.dumps(
            {"task_id": task_id, "profile": args.profile, "metrics_path": str(metrics_path), "targets": results},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
