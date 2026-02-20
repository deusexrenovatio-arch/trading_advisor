from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"


def _load_policy(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("policy file must be a YAML object")
    return payload


def _normalize_command(raw: list[Any], python_executable: str) -> list[str]:
    out: list[str] = []
    for token in raw:
        value = str(token)
        if value == "{python}":
            out.append(python_executable)
        else:
            out.append(value)
    return out


def run(policy_path: Path) -> int:
    if not policy_path.exists():
        print(f"architecture policy not found: {policy_path.as_posix()}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    try:
        policy = _load_policy(policy_path)
    except Exception as exc:
        print(f"architecture policy validation failed: {exc}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    if policy.get("version") != 1:
        print(f"architecture policy validation failed: unsupported version {policy.get('version')!r}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    checks = policy.get("checks")
    if not isinstance(checks, list) or not checks:
        print("architecture policy validation failed: checks must be a non-empty list")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    blocking_failures: list[str] = []
    for idx, check in enumerate(checks):
        if not isinstance(check, dict):
            print(f"architecture policy check[{idx}] invalid: must be an object")
            return 1
        check_id = str(check.get("id", "")).strip() or f"check-{idx}"
        raw_command = check.get("command")
        if not isinstance(raw_command, list) or not raw_command:
            print(f"architecture policy check '{check_id}' invalid: command must be non-empty list")
            return 1
        command = _normalize_command(raw_command, sys.executable)
        blocking = bool(check.get("blocking", True))
        print(f">>> policy[{check_id}] {' '.join(command)}")
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            level = "BLOCKING" if blocking else "NON-BLOCKING"
            print(f"policy[{check_id}] failed ({level})")
            if blocking:
                blocking_failures.append(check_id)

    if blocking_failures:
        print(
            "architecture policy: FAILED (blocking checks: "
            + ", ".join(sorted(blocking_failures))
            + ")"
        )
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    print("architecture policy: OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run architecture policy-as-code checks.")
    parser.add_argument("--policy", default="configs/architecture_policy.yaml")
    args = parser.parse_args()
    sys.exit(run(Path(args.policy)))


if __name__ == "__main__":
    main()
