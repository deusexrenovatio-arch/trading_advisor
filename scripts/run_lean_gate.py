from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"
DEPRECATION_NOTICE = (
    "run_lean_gate is deprecated and currently wraps run_loop_gate. "
    "Use scripts/run_loop_gate.py directly."
)


def _run(cmd: list[str]) -> int:
    printable = " ".join(cmd)
    print(f">>> {printable}", flush=True)
    completed = subprocess.run(cmd, check=False)
    return int(completed.returncode)


def _run_compat_fallback() -> int:
    print(
        "lean gate wrapper: run_loop_gate.py not found; "
        "using minimal compatibility fallback sequence."
    )
    fallback_commands = [
        [sys.executable, "scripts/agent_process_telemetry.py", "first-patch"],
        [sys.executable, "scripts/sync_task_outcomes.py"],
        [sys.executable, "scripts/validate_task_outcomes.py"],
        [sys.executable, "scripts/validate_process_regressions.py"],
    ]
    for command in fallback_commands:
        if not Path(command[1]).exists():
            continue
        code = _run(command)
        if code != 0:
            print(f"lean gate wrapper: FAILED\nremediation: see {REMEDIATION_DOC}")
            return code
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compatibility wrapper for loop gate during migration."
    )
    parser.add_argument("--summary-file", default=None)
    parser.add_argument(
        "--skip-metrics",
        action="store_true",
        help="Deprecated compatibility flag; retained for transition only.",
    )
    parser.add_argument(
        "--mapping",
        default="configs/change_surface_mapping.yaml",
        help="Change-surface mapping file path.",
    )
    args = parser.parse_args()

    print(f"lean gate wrapper: {DEPRECATION_NOTICE}")
    if args.skip_metrics:
        print("lean gate wrapper: --skip-metrics is deprecated and has no effect")

    loop_gate_path = Path("scripts/run_loop_gate.py")
    if loop_gate_path.exists():
        command = [
            sys.executable,
            str(loop_gate_path),
            "--mapping",
            args.mapping,
            "--from-git",
            "--git-ref",
            "HEAD",
        ]
        if args.summary_file:
            command.extend(["--summary-file", str(args.summary_file)])
        code = _run(command)
    else:
        if args.summary_file:
            print(
                "lean gate wrapper: --summary-file is ignored in fallback mode "
                "(run_loop_gate.py missing)"
            )
        code = _run_compat_fallback()

    if code != 0:
        print(f"lean gate wrapper: FAILED\nremediation: see {REMEDIATION_DOC}")
        return code
    print("lean gate wrapper: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
