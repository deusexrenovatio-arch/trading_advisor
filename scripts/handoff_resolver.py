from __future__ import annotations

import re
from pathlib import Path

ACTIVE_TASK_NOTE_HEADING = "## Active Task Note"
PATH_LINE_RE = re.compile(r"^-+\s*path\s*:\s*(.+?)\s*$", re.IGNORECASE)
STATUS_LINE_RE = re.compile(r"^-+\s*status\s*:\s*(.+?)\s*$", re.IGNORECASE)
MARKDOWN_LINK_RE = re.compile(r"\[.*?\]\((.+?)\)")


def _extract_path_value(raw: str) -> str | None:
    stripped = raw.strip()
    match = PATH_LINE_RE.match(stripped)
    if not match:
        return None
    value = match.group(1).strip()
    link_match = MARKDOWN_LINK_RE.search(value)
    if link_match:
        value = link_match.group(1).strip()
    return value.strip("`").strip()


def _extract_status_value(raw: str) -> str | None:
    stripped = raw.strip()
    match = STATUS_LINE_RE.match(stripped)
    if not match:
        return None
    return match.group(1).strip().strip("`").strip()


def extract_active_task_note_path(lines: list[str]) -> str | None:
    in_section = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("## "):
            in_section = stripped == ACTIVE_TASK_NOTE_HEADING
            continue
        if not in_section:
            continue
        resolved = _extract_path_value(stripped)
        if resolved:
            return resolved
    return None


def extract_active_task_note_status(lines: list[str]) -> str | None:
    in_section = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("## "):
            in_section = stripped == ACTIVE_TASK_NOTE_HEADING
            continue
        if not in_section:
            continue
        resolved = _extract_status_value(stripped)
        if resolved:
            return resolved
    return None


def resolve_task_note_path(handoff_path: Path) -> tuple[Path, bool]:
    lines = handoff_path.read_text(encoding="utf-8").splitlines()
    active_note = extract_active_task_note_path(lines)
    if not active_note:
        return handoff_path, False
    candidate = Path(active_note)
    if not candidate.is_absolute():
        candidate = (handoff_path.parent.parent / candidate).resolve()
    if not candidate.exists():
        return handoff_path, False
    return candidate, True


def read_task_note_lines(handoff_path: Path) -> tuple[Path, list[str], bool]:
    target_path, is_pointer = resolve_task_note_path(handoff_path)
    return target_path, target_path.read_text(encoding="utf-8").splitlines(), is_pointer
