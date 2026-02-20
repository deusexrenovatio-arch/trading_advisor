from __future__ import annotations

import argparse
import subprocess
import sys


REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"


def run(targets: list[str]) -> int:
    command = [sys.executable, "-m", "ruff", "check", *targets]
    print(f">>> {' '.join(command)}")
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        print(f"python style validation failed (targets={','.join(targets)})")
        print(f"remediation: see {REMEDIATION_DOC}")
        return int(completed.returncode)
    print(f"python style validation: OK (targets={','.join(targets)})")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Python style gate using ruff.")
    parser.add_argument(
        "--targets",
        nargs="+",
        default=["src", "tests", "scripts"],
        help="Repository paths to lint with ruff check.",
    )
    args = parser.parse_args()
    raise SystemExit(run([str(item) for item in args.targets]))


if __name__ == "__main__":
    main()
