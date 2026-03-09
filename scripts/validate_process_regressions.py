from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_process_telemetry import (
    ROLLING_WINDOW_SIZE,
    TASK_OUTCOMES_REMEDIATION_DOC,
    compute_process_rollup,
    default_task_outcomes_path,
    load_task_outcomes,
)


def run(*, task_outcomes_path: Path, focus: str | None, report: Path | None) -> int:
    payload = load_task_outcomes(task_outcomes_path)
    rollup = compute_process_rollup(payload, window_size=ROLLING_WINDOW_SIZE)
    threshold_results = rollup["threshold_results"]

    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Process Regression Validation", ""]
        lines.append(f"- burn_in_complete: {rollup['burn_in_complete']}")
        lines.append(f"- completed_tasks_count: {rollup['completed_tasks_count']}")
        lines.append("")
        for dimension, details in sorted(threshold_results.items()):
            status = str(details.get("status") or ("pass" if details.get("ok") else "fail"))
            lines.append(f"## {dimension}")
            lines.append(f"- status: {status}")
            lines.append(f"- blocking: {bool(details.get('blocking'))}")
            for check in details["checks"]:
                lines.append(
                    "- "
                    f"{check['metric']} {check['operator']} {check['threshold']:.2f} "
                    f"(actual={check['actual']:.2f}, passed={check['passed']})"
                )
            lines.append("")
        report.write_text("\n".join(lines), encoding="utf-8")

    if not rollup["burn_in_complete"]:
        print(
            "process regressions validation: OK "
            f"(burn-in {rollup['completed_tasks_count']}/{ROLLING_WINDOW_SIZE})"
        )
        return 0

    dimensions = [focus] if focus else sorted(threshold_results)
    failures: list[str] = []
    for dimension in dimensions:
        if dimension and bool(threshold_results[dimension].get("blocking")):
            failures.append(dimension)

    if failures:
        print("process regressions validation failed:")
        for dimension in failures:
            for check in threshold_results[dimension]["checks"]:
                if check["passed"]:
                    continue
                print(
                    "- "
                    f"{dimension}: {check['metric']} {check['operator']} {check['threshold']:.2f} "
                    f"(actual={check['actual']:.2f})"
                )
        print(f"remediation: see {TASK_OUTCOMES_REMEDIATION_DOC}")
        return 1

    remediating = [
        dimension
        for dimension in dimensions
        if threshold_results[dimension].get("status") == "acknowledged_debt"
    ]

    if remediating:
        joined = ",".join(remediating)
        print(
            "process regressions validation: OK "
            f"(window={rollup['current_window_count']} acknowledged_debt={joined})"
        )
    else:
        print(
            "process regressions validation: OK "
            f"(window={rollup['current_window_count']} burn_in_complete={rollup['burn_in_complete']})"
        )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate rolling process telemetry thresholds.")
    parser.add_argument("--task-outcomes-path", default=str(default_task_outcomes_path()))
    parser.add_argument("--focus", choices=("decision-quality", "context-efficiency", "self-learning"))
    parser.add_argument("--report", default=None)
    args = parser.parse_args()
    sys.exit(
        run(
            task_outcomes_path=Path(args.task_outcomes_path),
            focus=args.focus,
            report=Path(args.report) if args.report else None,
        )
    )


if __name__ == "__main__":
    main()
