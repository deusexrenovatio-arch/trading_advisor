from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

def collect_changed_files(
    *,
    base_ref: str | None,
    head_ref: str | None,
    git_ref: str | None,
    from_git: bool,
    changed_files: list[str],
    from_stdin: bool,
) -> list[str]:
    files = list(changed_files)
    if base_ref and head_ref:
        diff = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}..{head_ref}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if diff.returncode == 0:
            files.extend(line.strip() for line in diff.stdout.splitlines() if line.strip())
    elif from_git:
        ref = git_ref or "HEAD"
        diff = subprocess.run(
            ["git", "diff", "--name-only", ref],
            check=False,
            capture_output=True,
            text=True,
        )
        if diff.returncode == 0:
            files.extend(line.strip() for line in diff.stdout.splitlines() if line.strip())
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            check=False,
            capture_output=True,
            text=True,
        )
        if untracked.returncode == 0:
            files.extend(line.strip() for line in untracked.stdout.splitlines() if line.strip())
    if from_stdin:
        files.extend(line.strip() for line in sys.stdin.read().splitlines() if line.strip())

    normalized: list[str] = []
    seen: set[str] = set()
    for item in files:
        candidate = item.replace("\\", "/").strip()
        marker = candidate.lower()
        if not marker or marker in seen:
            continue
        seen.add(marker)
        normalized.append(candidate)
    return normalized


def run_command(command: str) -> int:
    print(f">>> {command}", flush=True)
    completed = subprocess.run(command, shell=True, check=False)
    return int(completed.returncode)


def run_commands(commands: list[str]) -> tuple[int, str | None]:
    for command in commands:
        code = run_command(command)
        if code != 0:
            return code, command
    return 0, None


def scope_validate_task_outcomes_command(
    command: str,
    *,
    base_sha: str | None,
    head_sha: str | None,
    changed_files: list[str],
) -> str:
    def _normalize(token: str) -> str:
        return token.replace("\\", "/").strip().lower()

    try:
        parts = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return command
    normalized = [_normalize(token) for token in parts]
    if not any(token.endswith("scripts/validate_task_outcomes.py") for token in normalized):
        return command
    if "--base-sha" in normalized or "--changed-files" in normalized:
        return command

    scoped_parts = list(parts)
    if base_sha and head_sha:
        scoped_parts.extend(["--base-sha", base_sha, "--head-sha", head_sha])
    elif changed_files:
        scoped_parts.append("--changed-files")
        scoped_parts.extend(changed_files)
    else:
        return command

    if os.name == "nt":
        return subprocess.list2cmdline(scoped_parts)
    return shlex.join(scoped_parts)


def write_summary(
    *,
    summary_file: str | None,
    gate_name: str,
    surface_result: dict[str, Any],
    commands: list[str],
) -> None:
    if not summary_file:
        return
    summary_path = Path(summary_file)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"## {gate_name}",
        "",
        f"- Primary surface: `{surface_result['primary_surface']}`",
        f"- Surfaces: `{', '.join(surface_result['surfaces'])}`",
        f"- Docs only: `{surface_result['docs_only']}`",
        f"- Changed files: `{len(surface_result['changed_files'])}`",
        "",
        "### Commands",
    ]
    for command in commands:
        lines.append(f"- `{command}`")
    lines.append("")
    with summary_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
