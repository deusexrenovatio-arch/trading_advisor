from __future__ import annotations

import argparse
import subprocess
import sys

REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"


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
        [py, "scripts/validate_plans.py"],
        [py, "scripts/validate_agent_memory.py"],
        [py, "scripts/validate_session_handoff.py"],
        [py, "scripts/validate_harness_guideline.py"],
        [py, "scripts/validate_architecture_policy.py"],
        [py, "scripts/validate_test_cases.py"],
        [py, "scripts/validate_user_needs_catalog.py"],
        [py, "scripts/validate_skills.py"],
        [py, "scripts/validate_codeowners.py"],
        [py, "scripts/validate_flaky_policy.py"],
        [py, "scripts/validate_observability_stack.py"],
        [py, "scripts/validate_taste_invariants.py"],
        [py, "scripts/validate_python_style.py"],
        [py, "scripts/validate_structured_logging.py"],
        [py, "scripts/validate_dependency_decisions.py"],
        [py, "scripts/validate_governance_remediation.py"],
    ]

    if not args.skip_metrics:
        metrics_cmd = [py, "scripts/harness_baseline_metrics.py"]
        if args.summary_file:
            metrics_cmd.extend(["--summary-file", str(args.summary_file)])
        commands.append(metrics_cmd)

    for cmd in commands:
        code = _run(cmd)
        if code != 0:
            print(
                "lean gate: FAILED "
                f"(command={' '.join(cmd)})\n"
                f"remediation: see {REMEDIATION_DOC}"
            )
            return code

    print("lean gate: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
