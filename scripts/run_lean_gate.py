from __future__ import annotations

import argparse
import subprocess
import sys

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

    command = [
        sys.executable,
        "scripts/run_loop_gate.py",
        "--mapping",
        args.mapping,
        "--from-git",
        "--git-ref",
        "HEAD",
    ]
    if args.summary_file:
        command.extend(["--summary-file", str(args.summary_file)])

    code = _run(command)
    if code != 0:
        print(f"lean gate wrapper: FAILED\nremediation: see {REMEDIATION_DOC}")
        return code
    print("lean gate wrapper: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
