from __future__ import annotations

import argparse
from pathlib import Path

from agent_process_telemetry import (
    default_events_path,
    default_session_handoff_path,
    default_state_path,
    is_non_trivial_diff,
    record_first_patch,
)
from compute_change_surface import compute_surface
from gate_common import collect_changed_files, run_commands, write_summary
from task_session import check_active_session


REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"


def _ensure_active_session() -> int:
    code, message, _payload = check_active_session()
    if code == 0:
        return 0
    print(f"loop gate: FAILED (inactive task session: {message})")
    print("loop gate: run `python scripts/task_session.py begin --request \"<request>\"` first")
    print(f"remediation: see {REMEDIATION_DOC}")
    return code


def _record_first_patch_if_needed(changed_files: list[str]) -> int:
    if not changed_files or not is_non_trivial_diff(changed_files):
        return 0
    recorded, active = record_first_patch(
        events_path=default_events_path(),
        state_path=default_state_path(),
        handoff_path=default_session_handoff_path(),
    )
    if recorded and isinstance(active, dict):
        print(
            "loop gate: first_patch "
            f"(task_id={active['task_id']} time_to_first_patch_sec={active['time_to_first_patch_sec']})"
        )
    return 0


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
    parser.add_argument("--skip-session-check", action="store_true")
    args = parser.parse_args()

    if not args.skip_session_check:
        code = _ensure_active_session()
        if code != 0:
            return code

    changed_files = collect_changed_files(
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        git_ref=args.git_ref,
        from_git=args.from_git,
        changed_files=list(args.changed_files),
        from_stdin=args.stdin,
    )

    if (
        not args.skip_session_check
        and not args.base_ref
        and not args.head_ref
    ):
        _record_first_patch_if_needed(changed_files)

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
