from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_process_telemetry import (
    collect_diff_between_refs,
    compute_process_rollup,
    default_task_outcomes_path,
    get_repo_root,
    is_non_trivial_diff,
    load_task_outcomes,
    render_rollup_markdown,
)


def run(
    *,
    task_outcomes_path: Path,
    output: Path,
    summary_file: Path | None,
    base_sha: str | None,
    head_sha: str | None,
) -> int:
    payload = load_task_outcomes(task_outcomes_path)
    rollup = compute_process_rollup(payload)
    report = render_rollup_markdown(rollup)
    if base_sha and head_sha:
        changed_files = collect_diff_between_refs(get_repo_root(), base_sha, head_sha)
        diff_lines = [
            "## Diff Window",
            "",
            f"- changed_files_count: {len(changed_files)}",
            f"- non_trivial_diff: {is_non_trivial_diff(changed_files)}",
            f"- handoff_updated: {'docs/session_handoff.md' in changed_files}",
            f"- task_outcomes_updated: {'memory/task_outcomes.yaml' in changed_files}",
            "",
        ]
        report = report.rstrip() + "\n\n" + "\n".join(diff_lines) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"process improvement report written: {output.as_posix()}")

    if summary_file is not None:
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        with summary_file.open("a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a process-improvement report from task outcomes.")
    parser.add_argument("--task-outcomes-path", default=str(default_task_outcomes_path()))
    parser.add_argument("--output", default="process-improvement-report.md")
    parser.add_argument("--summary-file", default=None)
    parser.add_argument("--base-sha", default=None)
    parser.add_argument("--head-sha", default=None)
    args = parser.parse_args()
    summary_path = Path(args.summary_file) if args.summary_file else None
    sys.exit(
        run(
            task_outcomes_path=Path(args.task_outcomes_path),
            output=Path(args.output),
            summary_file=summary_path,
            base_sha=args.base_sha,
            head_sha=args.head_sha,
        )
    )


if __name__ == "__main__":
    main()
