from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from handoff_resolver import read_task_note_lines

REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"
INCIDENT_POLICY_PATH = Path("configs/agent_incident_policy.yaml")
REQUIRED_CONTRACT_ITEMS = (
    "- objective:",
    "- in scope:",
    "- out of scope:",
    "- constraints:",
    "- done evidence:",
    "- priority rule:",
)
MAX_ATTEMPTS_RE = re.compile(r"^- max same-path attempts:\s*(\d+)\s*$")
REQUIRED_REPORT_ITEMS = (
    "1. confirmed coverage:",
    "2. missing or risky scenarios:",
    "3. resource/time risks and chosen controls:",
    "4. highest-priority fixes or follow-ups:",
)
REQUIRED_REPETITION_ITEMS = (
    "- max same-path attempts:",
    "- stop trigger:",
    "- reset action:",
    "- new search space:",
    "- next probe:",
)


def _find_heading_line(lines: list[str], heading: str) -> int:
    for idx, raw in enumerate(lines):
        if raw.strip() == heading:
            return idx
    return -1


def _section_lines(lines: list[str], heading: str) -> list[str]:
    start = _find_heading_line(lines, heading)
    if start < 0:
        return []
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if lines[idx].strip().startswith("## "):
            end = idx
            break
    return lines[start + 1 : end]


def _normalize(lines: list[str]) -> list[str]:
    return [line.strip().lower() for line in lines if line.strip()]


def _missing_prefixes(section_lines: list[str], required_prefixes: tuple[str, ...]) -> list[str]:
    normalized = _normalize(section_lines)
    missing: list[str] = []
    for prefix in required_prefixes:
        if not any(line.startswith(prefix) for line in normalized):
            missing.append(prefix)
    return missing


def _load_policy_max_same_path_attempts(errors: list[str]) -> int | None:
    if not INCIDENT_POLICY_PATH.exists():
        errors.append(f"incident policy missing: {INCIDENT_POLICY_PATH.as_posix()}")
        return None
    payload = yaml.safe_load(INCIDENT_POLICY_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        errors.append("incident policy is not a YAML object")
        return None
    incident = payload.get("incident") or {}
    if not isinstance(incident, dict):
        errors.append("incident policy invalid: 'incident' must be object")
        return None
    raw = incident.get("max_same_path_attempts")
    if raw is None:
        return None
    try:
        value = int(raw)
        if value < 1:
            raise ValueError
        return value
    except (TypeError, ValueError):
        errors.append("incident policy invalid: max_same_path_attempts must be positive integer")
        return None


def _extract_max_same_path_attempts(repetition_section: list[str], errors: list[str]) -> int | None:
    for raw in repetition_section:
        normalized = raw.strip().lower()
        match = MAX_ATTEMPTS_RE.match(normalized)
        if match:
            try:
                value = int(match.group(1))
                if value < 1:
                    raise ValueError
                return value
            except ValueError:
                errors.append("Repetition Control has invalid max same-path attempts value")
                return None
    errors.append("Repetition Control missing numeric '- max same-path attempts: <n>'")
    return None


def run(path: Path) -> int:
    if not path.exists():
        print(f"task request contract validation failed: missing {path.as_posix()}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    target_path, lines, is_pointer = read_task_note_lines(path)
    errors: list[str] = []

    contract_heading = "## Task Request Contract"
    report_heading = "## First-Time-Right Report"
    repetition_heading = "## Repetition Control"

    contract_section = _section_lines(lines, contract_heading)
    report_section = _section_lines(lines, report_heading)
    repetition_section = _section_lines(lines, repetition_heading)

    if not contract_section:
        errors.append(f"missing section: {contract_heading}")
    if not report_section:
        errors.append(f"missing section: {report_heading}")
    if not repetition_section:
        errors.append(f"missing section: {repetition_heading}")

    if contract_section:
        missing_contract = _missing_prefixes(contract_section, REQUIRED_CONTRACT_ITEMS)
        for prefix in missing_contract:
            errors.append(f"missing contract item in {contract_heading}: {prefix}")

    if report_section:
        missing_report = _missing_prefixes(report_section, REQUIRED_REPORT_ITEMS)
        for prefix in missing_report:
            errors.append(f"missing report item in {report_heading}: {prefix}")

    if repetition_section:
        missing_repetition = _missing_prefixes(repetition_section, REQUIRED_REPETITION_ITEMS)
        for prefix in missing_repetition:
            errors.append(f"missing repetition item in {repetition_heading}: {prefix}")
        contract_max_attempts = _extract_max_same_path_attempts(repetition_section, errors)
        policy_max_attempts = _load_policy_max_same_path_attempts(errors)
        if (
            contract_max_attempts is not None
            and policy_max_attempts is not None
            and contract_max_attempts > policy_max_attempts
        ):
            errors.append(
                "Repetition Control max same-path attempts "
                f"{contract_max_attempts} exceeds policy max_same_path_attempts {policy_max_attempts}"
            )

    if errors:
        print("task request contract validation failed:")
        for item in errors:
            print(f"- {item}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    print(
        "task request contract validation: OK "
        f"(source={target_path.as_posix()} pointer_mode={is_pointer} "
        f"contract_items={len(REQUIRED_CONTRACT_ITEMS)} "
        f"report_items={len(REQUIRED_REPORT_ITEMS)} "
        f"repetition_items={len(REQUIRED_REPETITION_ITEMS)})"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate task request contract and first-time-right report in session handoff."
    )
    parser.add_argument("--path", default="docs/session_handoff.md")
    args = parser.parse_args()
    sys.exit(run(Path(args.path)))


if __name__ == "__main__":
    main()
