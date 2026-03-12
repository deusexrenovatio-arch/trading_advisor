from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

from handoff_resolver import (
    extract_active_task_note_path,
    extract_active_task_note_status,
    read_task_note_lines,
)

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
ACTIVE_HOT_DOC = "docs/session_handoff.md"


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


def _normalize_changed_files(paths: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        normalized = str(raw).replace("\\", "/").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _collect_changed_files(
    *,
    base_sha: str | None,
    head_sha: str | None,
    changed_files_override: list[str] | None,
) -> list[str]:
    if changed_files_override is not None:
        return _normalize_changed_files(changed_files_override)
    if not base_sha or not head_sha:
        return []
    completed = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}..{head_sha}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return []
    rows = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return _normalize_changed_files(rows)


def _relative_marker(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix().lower()
    except ValueError:
        return None


def _extract_archive_marker(path_text: str) -> str | None:
    normalized = str(path_text).replace("\\", "/").strip().lower()
    marker = "/docs/tasks/archive/"
    if marker in normalized:
        return "docs/tasks/archive/" + normalized.split(marker, 1)[1].lstrip("/")
    if normalized.startswith("docs/tasks/archive/"):
        return normalized
    return None


def _enforce_pointer_freshness(
    *,
    path: Path,
    target_path: Path,
    is_pointer: bool,
    handoff_lines: list[str],
    changed_files: list[str],
    errors: list[str],
) -> None:
    if not is_pointer:
        return

    active_note_path = extract_active_task_note_path(handoff_lines) or ""
    active_note_status = (extract_active_task_note_status(handoff_lines) or "").strip().lower()
    note_path_marker = _extract_archive_marker(active_note_path)
    target_marker = _extract_archive_marker(target_path.as_posix())
    archived_pointer = bool(note_path_marker or target_marker)
    closed_status = active_note_status in {"completed", "archived"}
    if not archived_pointer and not closed_status:
        return

    changed = set(changed_files)
    repo_root = path.resolve().parent.parent
    target_rel = _relative_marker(target_path, repo_root)
    handoff_rel = _relative_marker(path, repo_root) or ACTIVE_HOT_DOC
    note_markers = {
        marker
        for marker in {
            note_path_marker,
            target_marker,
            target_rel,
            active_note_path.replace("\\", "/").strip().lower() or None,
        }
        if marker
    }

    if (
        handoff_rel in changed
        and any(marker in changed for marker in note_markers)
    ):
        return

    errors.append(
        "Active Task Note points to an archived/completed note without scoped closeout evidence. "
        "Create a new active note or include docs/session_handoff.md plus archived note updates in this diff."
    )


def run(
    path: Path,
    *,
    base_sha: str | None = None,
    head_sha: str | None = None,
    changed_files_override: list[str] | None = None,
) -> int:
    if not path.exists():
        print(f"task request contract validation failed: missing {path.as_posix()}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    handoff_lines = path.read_text(encoding="utf-8").splitlines()
    target_path, lines, is_pointer = read_task_note_lines(path)
    changed_files = _collect_changed_files(
        base_sha=base_sha,
        head_sha=head_sha,
        changed_files_override=changed_files_override,
    )
    errors: list[str] = []
    _enforce_pointer_freshness(
        path=path,
        target_path=target_path,
        is_pointer=is_pointer,
        handoff_lines=handoff_lines,
        changed_files=changed_files,
        errors=errors,
    )

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
    parser.add_argument("--base-sha", default=None)
    parser.add_argument("--head-sha", default=None)
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--changed-files", nargs="*", default=[])
    args = parser.parse_args()
    changed_files_override: list[str] | None = None
    if args.base_sha and args.head_sha:
        changed_files_override = None
    elif args.stdin or args.changed_files:
        stdin_items = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()] if args.stdin else []
        changed_files_override = [*list(args.changed_files), *stdin_items]
    sys.exit(
        run(
            Path(args.path),
            base_sha=args.base_sha,
            head_sha=args.head_sha,
            changed_files_override=changed_files_override,
        )
    )


if __name__ == "__main__":
    main()
