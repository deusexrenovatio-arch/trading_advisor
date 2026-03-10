from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from compute_change_surface import compute_surface
from gate_common import collect_changed_files, run_command, run_commands, write_summary


REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"


def _run_worktree_guard() -> int:
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        print("loop gate: skip worktree_guard (powershell not found)")
        return 0
    command = f'{shell} -ExecutionPolicy Bypass -File scripts/worktree_guard.ps1 -Action Check'
    return run_command(command)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run scoped hot-loop governance gate.")
    parser.add_argument("--mapping", default="configs/change_surface_mapping.yaml")
    parser.add_argument("--from-git", action="store_true")
    parser.add_argument("--git-ref", default="HEAD")
    parser.add_argument("--base-ref", default=None)
    parser.add_argument("--head-ref", default=None)
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--changed-files", nargs="*", default=[])
    parser.add_argument("--summary-file", default=None)
    parser.add_argument("--skip-worktree-guard", action="store_true")
    args = parser.parse_args()

    if not args.skip_worktree_guard:
        code = _run_worktree_guard()
        if code != 0:
            print(f"loop gate: FAILED (worktree_guard)\nremediation: see {REMEDIATION_DOC}")
            return code

    changed_files = collect_changed_files(
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        git_ref=args.git_ref,
        from_git=args.from_git,
        changed_files=list(args.changed_files),
        from_stdin=args.stdin,
    )
    surface = compute_surface(changed_files, mapping_path=Path(args.mapping))
    commands = surface["commands"]["loop"]
    code, failed_command = run_commands(commands)
    write_summary(
        summary_file=args.summary_file,
        gate_name="loop gate",
        surface_result=surface,
        commands=commands,
    )
    if code != 0:
        print(
            "loop gate: FAILED "
            f"(command={failed_command})\n"
            f"remediation: see {REMEDIATION_DOC}"
        )
        return code

    print(
        "loop gate: OK "
        f"(primary_surface={surface['primary_surface']} surfaces={','.join(surface['surfaces'])})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
