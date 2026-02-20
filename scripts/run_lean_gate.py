from __future__ import annotations

import argparse
import subprocess
import sys


def _run(cmd: list[str]) -> int:
    printable = " ".join(cmd)
    print(f">>> {printable}", flush=True)
    completed = subprocess.run(cmd, check=False)
    return int(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run lightweight governance gates for short coding loops."
    )
    parser.add_argument(
        "--summary-file",
        default=None,
        help="Optional path for metrics markdown append (for CI summary).",
    )
    parser.add_argument(
        "--skip-metrics",
        action="store_true",
        help="Skip harness baseline metrics command.",
    )
    args = parser.parse_args()

    py = sys.executable
    commands: list[list[str]] = [
        [py, "scripts/sync_architecture_map.py", "--check"],
        [py, "scripts/validate_harness_guideline.py"],
        [py, "scripts/validate_import_boundaries.py"],
        [py, "scripts/validate_api_v2_contract_parity.py"],
        [py, "scripts/validate_test_cases.py"],
        [py, "scripts/validate_user_needs_catalog.py"],
        [py, "scripts/validate_skills.py"],
    ]

    if not args.skip_metrics:
        metrics_cmd = [py, "scripts/harness_baseline_metrics.py"]
        if args.summary_file:
            metrics_cmd.extend(["--summary-file", str(args.summary_file)])
        commands.append(metrics_cmd)

    for cmd in commands:
        code = _run(cmd)
        if code != 0:
            return code

    print("lean gate: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
