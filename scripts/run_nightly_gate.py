from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

from compute_change_surface import compute_surface
from gate_common import collect_changed_files, run_command, run_commands, write_summary


REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"


def _join_command(parts: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def _build_pr_gate_command(
    *,
    mapping: str,
    from_git: bool,
    git_ref: str | None,
    base_ref: str | None,
    head_ref: str | None,
) -> str:
    parts = [sys.executable, "scripts/run_pr_gate.py", "--mapping", mapping]
    if base_ref and head_ref:
        parts.extend(["--base-ref", base_ref, "--head-ref", head_ref])
    elif from_git:
        parts.extend(["--from-git", "--git-ref", git_ref or "HEAD"])
    else:
        parts.append("--from-git")
    return _join_command(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run nightly scoped governance gate.")
    parser.add_argument("--mapping", default="configs/change_surface_mapping.yaml")
    parser.add_argument("--from-git", action="store_true")
    parser.add_argument("--git-ref", default="HEAD")
    parser.add_argument("--base-ref", default=None)
    parser.add_argument("--head-ref", default=None)
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--changed-files", nargs="*", default=[])
    parser.add_argument("--summary-file", default=None)
    args = parser.parse_args()

    changed_files = collect_changed_files(
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        git_ref=args.git_ref,
        from_git=args.from_git,
        changed_files=list(args.changed_files),
        from_stdin=args.stdin,
    )
    surface = compute_surface(changed_files, mapping_path=Path(args.mapping))

    pr_command = _build_pr_gate_command(
        mapping=args.mapping,
        from_git=args.from_git,
        git_ref=args.git_ref,
        base_ref=args.base_ref,
        head_ref=args.head_ref,
    )
    pr_code = run_command(pr_command)
    if pr_code != 0:
        print(f"nightly gate: FAILED (command={pr_command})\nremediation: see {REMEDIATION_DOC}")
        return pr_code

    commands = [
        command
        for command in surface["commands"]["nightly"]
        if "scripts/run_pr_gate.py" not in command
    ]
    code, failed_command = run_commands(commands)
    write_summary(
        summary_file=args.summary_file,
        gate_name="nightly gate",
        surface_result=surface,
        commands=[pr_command, *commands],
    )
    if code != 0:
        print(
            "nightly gate: FAILED "
            f"(command={failed_command})\n"
            f"remediation: see {REMEDIATION_DOC}"
        )
        return code

    print(
        "nightly gate: OK "
        f"(primary_surface={surface['primary_surface']} surfaces={','.join(surface['surfaces'])})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
