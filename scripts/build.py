from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _run(cmd: list[str]) -> None:
    print(f"+ {' '.join(cmd)}", flush=True)
    subprocess.check_call(cmd, cwd=ROOT)


def _ensure_venv() -> Path:
    venv_python = _venv_python()
    if not venv_python.exists():
        _run([sys.executable, "-m", "venv", str(VENV_DIR)])
    _run([str(venv_python), "-m", "pip", "install", "-e", ".[dev]"])
    return venv_python


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    parser.add_argument(
        "--max-shares",
        type=int,
        default=1000,
        help="Limit number of shares for demo fetch (0 = no limit).",
    )
    parser.add_argument(
        "--collect-history",
        action="store_true",
        help="Start background history collector.",
    )
    parser.add_argument("--history-interval-sec", type=int, default=300)
    args = parser.parse_args()

    print("[build] Ensure venv + install deps.", flush=True)
    venv_python = _ensure_venv()
    print("[build] Run pipeline (this can take several minutes).", flush=True)
    pipeline_cmd = [str(venv_python), "scripts/pipeline_demo.py", "--config", args.config]
    if args.max_shares and args.max_shares > 0:
        pipeline_cmd.extend(["--max-shares", str(args.max_shares)])
    _run(pipeline_cmd)
    if args.collect_history:
        print("[build] Start history collector in background.", flush=True)
        history_cmd = [
            str(venv_python),
            "scripts/collect_history.py",
            "--config",
            args.config,
            "--loop",
            "--interval-sec",
            str(args.history_interval_sec),
        ]
        subprocess.Popen(history_cmd, cwd=ROOT)
    print("[build] Start server boundary.", flush=True)
    _run([str(venv_python), "scripts/run_server.py", "--config", args.config])


if __name__ == "__main__":
    main()
