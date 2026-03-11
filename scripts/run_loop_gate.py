from __future__ import annotations

import argparse
from pathlib import Path
import sys

from agent_process_telemetry import (
    default_events_path,
    default_session_handoff_path,
    default_state_path,
    is_non_trivial_diff,
    record_first_patch,
)
from compute_change_surface import compute_surface
from gate_common import (
    collect_changed_files,
    run_commands,
    scope_validate_task_outcomes_command,
    write_summary,
)
from task_session import check_active_session


REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"
NON_TRIVIAL_LOOP_VALIDATION_SCRIPTS = (
    "scripts/validate_task_request_contract.py",
    "scripts/validate_session_handoff.py",
)


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


def _normalize_command_text(command: str) -> str:
    return command.replace("\\", "/").strip().lower()


def _command_mentions_script(command: str, script_path: str) -> bool:
    return script_path.lower() in _normalize_command_text(command)


def _resolve_python_command(script_path: str) -> str:
    python_exec = sys.executable
    if " " in python_exec:
        python_exec = f"\"{python_exec}\""
    return f"{python_exec} {script_path}"


def _apply_non_trivial_loop_policy(
    commands: list[str],
    *,
    changed_files: list[str],
    docs_only: bool,
) -> tuple[list[str], bool]:
    require_contract_validation = is_non_trivial_diff(changed_files) and not docs_only
    filtered = [
        command
        for command in commands
        if require_contract_validation
        or not any(
            _command_mentions_script(command, script_path)
            for script_path in NON_TRIVIAL_LOOP_VALIDATION_SCRIPTS
        )
    ]

    if require_contract_validation:
        for script_path in NON_TRIVIAL_LOOP_VALIDATION_SCRIPTS:
            if any(_command_mentions_script(command, script_path) for command in filtered):
                continue
            filtered.append(_resolve_python_command(script_path))

    return filtered, require_contract_validation


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
    loop_commands, non_trivial_validation = _apply_non_trivial_loop_policy(
        list(surface["commands"]["loop"]),
        changed_files=changed_files,
        docs_only=bool(surface.get("docs_only")),
    )
    commands = [
        scope_validate_task_outcomes_command(
            command,
            base_sha=args.base_ref,
            head_sha=args.head_ref,
            changed_files=changed_files,
        )
        for command in loop_commands
    ]
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
        f"(primary_surface={surface['primary_surface']} "
        f"surfaces={','.join(surface['surfaces'])} "
        f"non_trivial_validation={non_trivial_validation})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
