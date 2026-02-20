from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml


SECTION_KEYS = ("decisions", "incidents", "patterns")
REQUIRED_FIELDS = {
    "decisions": ("id", "date", "title", "context", "decision", "impact"),
    "incidents": (
        "id",
        "date",
        "title",
        "symptom",
        "root_cause",
        "remediation",
        "remediation_type",
    ),
    "patterns": ("id", "date", "title", "pattern", "when_to_use"),
}


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("agent memory must be a YAML object")
    return payload


def _load_incident_policy(path: Path) -> tuple[set[str], set[str], list[str]]:
    if not path.exists():
        return set(), set(), [f"incident policy missing: {path.as_posix()}"]
    payload = _load_yaml(path)
    if payload.get("version") != 1:
        return set(), set(), [f"incident policy unsupported version: {payload.get('version')!r}"]
    incident = payload.get("incident") or {}
    if not isinstance(incident, dict):
        return set(), set(), ["incident policy invalid: 'incident' must be object"]
    allowed = incident.get("allowed_remediation_types") or []
    disallowed = incident.get("disallowed_remediation_types") or []
    if not isinstance(allowed, list):
        allowed = []
    if not isinstance(disallowed, list):
        disallowed = []
    allowed_set = {str(item).strip() for item in allowed if str(item).strip()}
    disallowed_set = {str(item).strip() for item in disallowed if str(item).strip()}
    errors: list[str] = []
    if not allowed_set:
        errors.append("incident policy invalid: allowed_remediation_types is empty")
    return allowed_set, disallowed_set, errors


def _parse_date(value: str, label: str, errors: list[str]) -> None:
    try:
        date.fromisoformat(value)
    except ValueError:
        errors.append(f"{label}: invalid ISO date '{value}'")


def run(path: Path, policy_path: Path) -> int:
    if not path.exists():
        print(f"agent memory validation failed: file missing {path.as_posix()}")
        print("remediation: see docs/runbooks/governance-remediation.md")
        return 1

    payload = _load_yaml(path)
    errors: list[str] = []
    allowed_types, disallowed_types, policy_errors = _load_incident_policy(policy_path)
    errors.extend(policy_errors)

    if payload.get("version") != 1:
        errors.append(f"unsupported version: {payload.get('version')!r} (expected 1)")

    updated_at = str(payload.get("updated_at", "")).strip()
    if not updated_at:
        errors.append("missing top-level field 'updated_at'")
    else:
        _parse_date(updated_at, "updated_at", errors)

    seen_ids: set[str] = set()
    total_entries = 0
    for section in SECTION_KEYS:
        rows = payload.get(section)
        if not isinstance(rows, list):
            errors.append(f"section '{section}' must be a list")
            continue
        for idx, row in enumerate(rows):
            label = f"{section}[{idx}]"
            if not isinstance(row, dict):
                errors.append(f"{label} must be an object")
                continue
            total_entries += 1
            for field in REQUIRED_FIELDS[section]:
                value = str(row.get(field, "")).strip()
                if not value:
                    errors.append(f"{label} missing required field '{field}'")
            entry_id = str(row.get("id", "")).strip()
            if entry_id:
                if entry_id in seen_ids:
                    errors.append(f"duplicate entry id: {entry_id}")
                seen_ids.add(entry_id)
            row_date = str(row.get("date", "")).strip()
            if row_date:
                _parse_date(row_date, f"{label}.date", errors)
            links = row.get("links")
            if links is not None:
                if not isinstance(links, list):
                    errors.append(f"{label}.links must be a list when present")
                else:
                    for link in links:
                        text = str(link).strip()
                        if not text:
                            errors.append(f"{label}.links contains empty value")
            if section == "incidents":
                remediation_type = str(row.get("remediation_type", "")).strip()
                if remediation_type:
                    if allowed_types and remediation_type not in allowed_types:
                        errors.append(
                            f"{label}.remediation_type '{remediation_type}' not allowed "
                            f"(allowed: {sorted(allowed_types)})"
                        )
                    if remediation_type in disallowed_types:
                        errors.append(
                            f"{label}.remediation_type '{remediation_type}' is disallowed"
                        )

    if total_entries == 0:
        errors.append("agent memory must contain at least one entry")

    if errors:
        print("agent memory validation failed:")
        for item in errors:
            print(f"- {item}")
        print("remediation: see docs/runbooks/governance-remediation.md")
        return 1

    print(
        "agent memory validation: OK "
        f"(entries={total_entries} updated_at={updated_at})"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate agent operational memory registry.")
    parser.add_argument("--path", default="memory/agent_memory.yaml")
    parser.add_argument("--policy", default="configs/agent_incident_policy.yaml")
    args = parser.parse_args()
    sys.exit(run(Path(args.path), Path(args.policy)))


if __name__ == "__main__":
    main()
