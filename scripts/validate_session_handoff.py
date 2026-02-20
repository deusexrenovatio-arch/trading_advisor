from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"
REQUIRED_HEADINGS = [
    "# Session Handoff",
    "## Goal",
    "## Current Delta",
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


def run(path: Path) -> int:
    if not path.exists():
        print(f"context budget validation failed: missing {path.as_posix()}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    non_empty_count = sum(1 for line in lines if line.strip())
    errors: list[str] = []

    if non_empty_count > MAX_TOTAL_NON_EMPTY_LINES:
        errors.append(
            f"non-empty line budget exceeded: {non_empty_count} > {MAX_TOTAL_NON_EMPTY_LINES}"
        )

    if not any(UPDATED_LINE_RE.match(line.strip()) for line in lines):
        errors.append("missing or invalid Updated line (expected: Updated: YYYY-MM-DD or YYYY-MM-DD HH:MM UTC)")

    for heading in REQUIRED_HEADINGS:
        if _find_heading_line(lines, heading) < 0:
            errors.append(f"missing heading: {heading}")

    for token in FORBIDDEN_TOKENS:
        if token in text:
            errors.append(f"forbidden high-context token found: {token}")

    delta_lines = _section_lines(lines, "## Current Delta")
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

    print(
        "context budget validation: OK "
        f"(non_empty_lines={non_empty_count} delta_bullets={len(delta_bullets)})"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate session handoff context budget contract.")
    parser.add_argument("--path", default="docs/session_handoff.md")
    args = parser.parse_args()
    sys.exit(run(Path(args.path)))


if __name__ == "__main__":
    main()
