from __future__ import annotations

import argparse
import subprocess
import sys


MODE_TO_GATE = {
    "quick": "scripts/run_loop_gate.py",
    "expanded": "scripts/run_pr_gate.py",
    "release": "scripts/run_nightly_gate.py",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local dev workflow mode against scoped gates.")
    parser.add_argument("--mode", choices=("quick", "expanded", "release"), default="quick")
    parser.add_argument("--mapping", default="configs/change_surface_mapping.yaml")
    parser.add_argument("--base-ref", default=None)
    parser.add_argument("--head-ref", default=None)
    parser.add_argument("--summary-file", default=None)
    args = parser.parse_args()

    gate_script = MODE_TO_GATE[args.mode]
    command = [
        sys.executable,
        gate_script,
        "--mapping",
        args.mapping,
    ]
    if args.base_ref and args.head_ref:
        command.extend(["--base-ref", args.base_ref, "--head-ref", args.head_ref])
    else:
        command.extend(["--from-git", "--git-ref", "HEAD"])
    if args.summary_file:
        command.extend(["--summary-file", args.summary_file])

    print(f">>> {' '.join(command)}", flush=True)
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
