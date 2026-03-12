from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from handoff_resolver import ACTIVE_TASK_NOTE_HEADING, read_task_note_lines

REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"
LEGACY_REQUIRED_HEADINGS = [
    "# Session Handoff",
    "## Goal",
    "## Current Delta",
    "## Task Outcome",
    "## Blockers",
    "## Next Step",
    "## Validation",
]
POINTER_SHIM_REQUIRED_HEADINGS = [
    "# Session Handoff",
    ACTIVE_TASK_NOTE_HEADING,
    "## Validation",
]
TASK_NOTE_REQUIRED_HEADINGS = [
    "## Goal",
    "## Current Delta",
    "## Task Outcome",
    "## Blockers",
    "## Next Step",
    "## Validation",
]
UPDATED_LINE_RE = re.compile(r"^Updated:\s*\d{4}-\d{2}-\d{2}(\s+\d{2}:\d{2}\s+UTC)?$")
FORBIDDEN_TOKENS = (
    "<INSTRUCTIONS>",
    "### Available skills",
)
MAX_TOTAL_NON_EMPTY_LINES = 80
MAX_POINTER_TASK_NON_EMPTY_LINES = 120
MAX_POINTER_SHIM_NON_EMPTY_LINES = 30
MAX_DELTA_BULLETS = 8
MAX_BULLET_LENGTH = 180


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


def _validate_required_headings(lines: list[str], headings: list[str], errors: list[str]) -> None:
    for heading in headings:
        if _find_heading_line(lines, heading) < 0:
            errors.append(f"missing heading: {heading}")


def _validate_updated_line(lines: list[str], errors: list[str], *, label: str) -> None:
    if not any(UPDATED_LINE_RE.match(line.strip()) for line in lines):
        errors.append(
            f"{label}: missing or invalid Updated line "
            "(expected: Updated: YYYY-MM-DD or YYYY-MM-DD HH:MM UTC)"
        )


def run(path: Path) -> int:
    if not path.exists():
        print(f"context budget validation failed: missing {path.as_posix()}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    shim_text = path.read_text(encoding="utf-8")
    shim_lines = shim_text.splitlines()
    target_path, target_lines, is_pointer = read_task_note_lines(path)
    target_text = "\n".join(target_lines)

    errors: list[str] = []

    if is_pointer:
        shim_non_empty = sum(1 for line in shim_lines if line.strip())
        if shim_non_empty > MAX_POINTER_SHIM_NON_EMPTY_LINES:
            errors.append(
                "session handoff pointer shim budget exceeded: "
                f"{shim_non_empty} > {MAX_POINTER_SHIM_NON_EMPTY_LINES}"
            )
        _validate_required_headings(shim_lines, POINTER_SHIM_REQUIRED_HEADINGS, errors)
        _validate_updated_line(shim_lines, errors, label="session handoff pointer shim")

        non_empty_count = sum(1 for line in target_lines if line.strip())
        if non_empty_count > MAX_POINTER_TASK_NON_EMPTY_LINES:
            errors.append(
                f"task note line budget exceeded: {non_empty_count} > {MAX_POINTER_TASK_NON_EMPTY_LINES}"
            )
        _validate_required_headings(target_lines, TASK_NOTE_REQUIRED_HEADINGS, errors)
        _validate_updated_line(target_lines, errors, label="task note")
        validation_lines = target_lines
        validation_text = target_text
    else:
        non_empty_count = sum(1 for line in shim_lines if line.strip())
        if non_empty_count > MAX_TOTAL_NON_EMPTY_LINES:
            errors.append(
                f"non-empty line budget exceeded: {non_empty_count} > {MAX_TOTAL_NON_EMPTY_LINES}"
            )
        _validate_required_headings(shim_lines, LEGACY_REQUIRED_HEADINGS, errors)
        _validate_updated_line(shim_lines, errors, label="session handoff")
        validation_lines = shim_lines
        validation_text = shim_text

    for token in FORBIDDEN_TOKENS:
        if token in validation_text:
            errors.append(f"forbidden high-context token found: {token}")

    delta_lines = _section_lines(validation_lines, "## Current Delta")
    delta_bullets = [line.strip() for line in delta_lines if line.strip().startswith("- ")]
    if not delta_bullets:
        errors.append("Current Delta section must include at least one bullet")
    if len(delta_bullets) > MAX_DELTA_BULLETS:
        errors.append(
            f"Current Delta bullet budget exceeded: {len(delta_bullets)} > {MAX_DELTA_BULLETS}"
        )
    for bullet in delta_bullets:
        if len(bullet) > MAX_BULLET_LENGTH:
            errors.append(
                f"Current Delta bullet too long ({len(bullet)} > {MAX_BULLET_LENGTH}): {bullet[:80]}..."
            )

    if errors:
        print("context budget validation failed:")
        for item in errors:
            print(f"- {item}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    non_empty_count = sum(1 for line in validation_lines if line.strip())
    print(
        "context budget validation: OK "
        f"(source={target_path.as_posix()} pointer_mode={is_pointer} "
        f"non_empty_lines={non_empty_count} delta_bullets={len(delta_bullets)})"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate session handoff context budget contract.")
    parser.add_argument("--path", default="docs/session_handoff.md")
    args = parser.parse_args()
    sys.exit(run(Path(args.path)))


if __name__ == "__main__":
    main()
