from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ESCALATION_RUNBOOK = "docs/runbooks/self-heal-escalation.md"


@dataclass(frozen=True)
class ActionResult:
    action: str
    command: list[str]
    returncode: int


def _run(command: list[str]) -> int:
    print(f">>> {' '.join(command)}", flush=True)
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


def _run_action(action: str, command: list[str]) -> ActionResult:
    rc = _run(command)
    return ActionResult(action=action, command=command, returncode=rc)


def _write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"self-heal report written: {path.as_posix()}")


def _append_summary(path: Path | None, payload: dict) -> None:
    if path is None:
        return
    lines = [
        "## Self-Heal Report",
        "",
        f"- timestamp_utc: {payload['timestamp_utc']}",
        f"- initial_pass: {payload['initial_pass']}",
        f"- final_pass: {payload['final_pass']}",
        f"- autofix_applied: {payload['autofix_applied']}",
        f"- escalation_required: {payload['escalation_required']}",
        "",
        "| Action | Return Code | Command |",
        "| --- | --- | --- |",
    ]
    for row in payload["actions"]:
        cmd = " ".join(row["command"])
        lines.append(f"| `{row['action']}` | {row['returncode']} | `{cmd}` |")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def run(report_path: Path, summary_file: Path | None) -> int:
    actions: list[ActionResult] = []

    initial_rc = _run([sys.executable, "scripts/run_lean_gate.py", "--skip-metrics"])
    initial_pass = initial_rc == 0

    autofix_applied = False
    final_pass = initial_pass
    if not initial_pass:
        remediation_actions = [
            (
                "sync-architecture-map",
                [sys.executable, "scripts/sync_architecture_map.py"],
            ),
            (
                "update-plans-timestamp-if-stale",
                [
                    sys.executable,
                    "scripts/update_plans_timestamp.py",
                    "--if-stale-days",
                    "30",
                ],
            ),
        ]
        for action, command in remediation_actions:
            result = _run_action(action, command)
            actions.append(result)
            if result.returncode == 0:
                autofix_applied = True

        final_rc = _run([sys.executable, "scripts/run_lean_gate.py", "--skip-metrics"])
        final_pass = final_rc == 0

    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "initial_pass": initial_pass,
        "final_pass": final_pass,
        "autofix_applied": autofix_applied,
        "escalation_required": not final_pass,
        "escalation_runbook": ESCALATION_RUNBOOK,
        "actions": [
            {
                "action": item.action,
                "command": item.command,
                "returncode": item.returncode,
            }
            for item in actions
        ],
    }
    _write_report(report_path, payload)
    _append_summary(summary_file, payload)

    if final_pass:
        print("self-heal: OK")
        return 0
    print(f"self-heal: FAILED (escalate via {ESCALATION_RUNBOOK})")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Attempt deterministic self-heal for governance drift.")
    parser.add_argument("--report", default="self-heal-report.json")
    parser.add_argument("--summary-file", default=None)
    args = parser.parse_args()
    summary = Path(args.summary_file) if args.summary_file else None
    raise SystemExit(run(Path(args.report), summary))


if __name__ == "__main__":
    main()
