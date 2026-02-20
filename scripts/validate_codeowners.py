from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml


REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("CODEOWNERS policy must be a YAML object")
    return payload


def _parse_codeowners(path: Path, owner_token: re.Pattern[str]) -> tuple[dict[str, list[str]], list[str]]:
    entries: dict[str, list[str]] = {}
    errors: list[str] = []

    for idx, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            errors.append(f"line {idx}: expected '<pattern> <owner...>'")
            continue
        pattern, owners = parts[0], parts[1:]
        if pattern in entries:
            errors.append(f"line {idx}: duplicate CODEOWNERS pattern '{pattern}'")
            continue
        for owner in owners:
            if not owner_token.match(owner):
                errors.append(f"line {idx}: invalid owner token '{owner}'")
        entries[pattern] = owners
    return entries, errors


def run(codeowners_path: Path, policy_path: Path) -> int:
    errors: list[str] = []

    if not codeowners_path.exists():
        print(f"codeowners validation failed: missing {codeowners_path.as_posix()}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1
    if not policy_path.exists():
        print(f"codeowners validation failed: missing policy {policy_path.as_posix()}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    policy = _load_yaml(policy_path)
    if policy.get("version") != 1:
        print(f"codeowners validation failed: unsupported policy version {policy.get('version')!r}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    required_patterns = policy.get("required_patterns") or []
    if not isinstance(required_patterns, list):
        required_patterns = []
    owner_token_regex = str(
        policy.get("owner_token_regex")
        or r"^(@[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)?|[^@\s]+@[^@\s]+)$"
    )
    owner_token = re.compile(owner_token_regex)

    entries, parse_errors = _parse_codeowners(codeowners_path, owner_token)
    errors.extend(parse_errors)

    if not entries:
        errors.append("CODEOWNERS file has no routing entries")

    for pattern in required_patterns:
        normalized = str(pattern).strip()
        if normalized and normalized not in entries:
            errors.append(f"missing required CODEOWNERS pattern: {normalized}")

    for pattern, owners in entries.items():
        if not owners:
            errors.append(f"pattern '{pattern}' has no owners")

    if errors:
        print("codeowners validation failed:")
        for item in errors:
            print(f"- {item}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    print(f"codeowners validation: OK (entries={len(entries)})")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate CODEOWNERS routing policy.")
    parser.add_argument("--path", default="CODEOWNERS")
    parser.add_argument("--policy", default="configs/codeowners_policy.yaml")
    args = parser.parse_args()
    sys.exit(run(Path(args.path), Path(args.policy)))


if __name__ == "__main__":
    main()
