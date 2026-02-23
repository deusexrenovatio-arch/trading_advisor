from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable


RELEVANT_SKILL_FILES = {
    "AGENTS.md",
    "docs/DEV_WORKFLOW.md",
    "docs/session_handoff.md",
    "docs/workflows/skill-governance-sync.md",
    "docs/checklists/first-time-right-gate.md",
    "docs/runbooks/governance-remediation.md",
    "scripts/run_lean_gate.py",
    "scripts/validate_skills.py",
}


def _run(cmd: list[str]) -> tuple[int, str]:
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode, completed.stdout.strip()


def _collect_staged_files() -> list[str]:
    code, output = _run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRD"]
    )
    if code != 0:
        print("[skill gate] warning: unable to read staged files, skipping decision check")
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def _is_relevant(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    if normalized in RELEVANT_SKILL_FILES:
        return True
    if normalized.startswith(".cursor/skills/") and normalized.endswith("/skill.md"):
        return True
    return False


def _run_decision(changed_files: Iterable[str], request: str) -> tuple[str, dict[str, object]]:
    cmd = [
        sys.executable,
        str(Path("scripts/skill_update_decision.py")),
        "--changed-files",
        *changed_files,
        "--request",
        request,
        "--json",
    ]
    code, output = _run(cmd)
    if code != 0:
        print("[skill gate] failed to run decision script")
        print(output)
        raise SystemExit(2)
    payload = json.loads(output)
    return payload["action"], payload


def _print_payload(payload: dict[str, object]) -> None:
    action = str(payload.get("action", "UNKNOWN"))
    print("[skill gate] decision:", action)
    print("[skill gate] confidence:", payload.get("confidence"), f"(score={payload.get('score')})")
    print("[skill gate] gates:")
    for gate in payload.get("gates", []):
        if not isinstance(gate, dict):
            continue
        print(
            f"- {gate.get('gate')} -> {gate.get('status')}: {gate.get('reason')}"
        )
    rationale = payload.get("rationale", [])
    if rationale:
        print("[skill gate] rationale:")
        for item in rationale:
            print(f"- {item}")
    next_steps = payload.get("next_steps", [])
    if next_steps:
        print("[skill gate] next steps:")
        for step in next_steps:
            print(f"- {step}")


def main() -> int:
    staged = _collect_staged_files()
    relevant = [path for path in staged if _is_relevant(path)]
    if not relevant:
        return 0

    request = os.environ.get(
        "SKILL_UPDATE_INTENT",
        " ".join(relevant),
    )
    action, payload = _run_decision(relevant, request)
    _print_payload(payload)

    strict_on_add_new = os.environ.get("SKILL_DECISION_STRICT", "0") == "1"

    if action == "NO_CHANGE":
        print(
            "[skill gate] commit blocked: model requires explicit scoping for this change."
        )
        print("[skill gate] rerun with detailed intent:")
        print('[skill gate]   $env:SKILL_UPDATE_INTENT="..."; git commit ...')
        return 1

    if action == "ADD_NEW" and strict_on_add_new:
        print(
            "[skill gate] commit blocked by strict mode: action is ADD_NEW."
        )
        print(
            "[skill gate] run onboarding flow with skill-creator -> skill-installer, "
            "then re-commit."
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
