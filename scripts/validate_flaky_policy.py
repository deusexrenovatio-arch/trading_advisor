from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("flaky policy must be a YAML object")
    return payload


def run(path: Path) -> int:
    if not path.exists():
        print(f"flaky policy validation failed: missing file {path.as_posix()}")
        print("remediation: see docs/runbooks/flaky-tests-policy.md")
        return 1

    payload = _load_yaml(path)
    errors: list[str] = []

    if payload.get("version") != 1:
        errors.append(f"unsupported version: {payload.get('version')!r} (expected 1)")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        errors.append("missing object field 'policy'")
        policy = {}

    owner = str(policy.get("owner", "")).strip()
    if not owner:
        errors.append("policy.owner is required")

    max_retries = int(policy.get("max_ci_retries", 0))
    if max_retries < 0 or max_retries > 2:
        errors.append("policy.max_ci_retries must be in range [0..2]")

    max_quarantined = int(policy.get("max_quarantined_tests", 0))
    if max_quarantined <= 0:
        errors.append("policy.max_quarantined_tests must be > 0")

    quarantine_ttl_days = int(policy.get("quarantine_ttl_days", 0))
    if quarantine_ttl_days <= 0 or quarantine_ttl_days > 30:
        errors.append("policy.quarantine_ttl_days must be in range [1..30]")

    followup_sla_days = int(policy.get("followup_sla_days", 0))
    if followup_sla_days <= 0 or followup_sla_days > 14:
        errors.append("policy.followup_sla_days must be in range [1..14]")

    required_issue_prefix = str(policy.get("required_tracking_issue_prefix", "")).strip()
    if not required_issue_prefix:
        errors.append("policy.required_tracking_issue_prefix is required")

    runbook = str(policy.get("escalation_runbook", "")).strip()
    if not runbook:
        errors.append("policy.escalation_runbook is required")
    elif not Path(runbook).exists():
        errors.append(f"policy.escalation_runbook path not found: {runbook}")

    if errors:
        print("flaky policy validation failed:")
        for item in errors:
            print(f"- {item}")
        print("remediation: see docs/runbooks/flaky-tests-policy.md")
        return 1

    print(
        "flaky policy validation: OK "
        f"(owner={owner} retries={max_retries} max_quarantined={max_quarantined})"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate flaky-tests policy configuration.")
    parser.add_argument("--path", default="configs/flaky_policy.yaml")
    args = parser.parse_args()
    sys.exit(run(Path(args.path)))


if __name__ == "__main__":
    main()
