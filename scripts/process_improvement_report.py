from __future__ import annotations
# ruff: noqa: E402

import argparse
import json
import sys
from pathlib import Path

from agent_process_telemetry import collect_diff_between_refs, default_task_outcomes_path, get_repo_root, is_non_trivial_diff

REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from moex_carry.governance.process_reports import build_process_report, load_task_outcomes, render_process_report_markdown


def run(
    *,
    task_outcomes_path: Path,
    output: Path,
    summary_file: Path | None,
    base_sha: str | None,
    head_sha: str | None,
    output_format: str,
    weeks: int,
    window_size: int,
) -> int:
    payload = load_task_outcomes(task_outcomes_path)
    report_payload = build_process_report(payload, window_size=window_size, max_weeks=weeks)
    diff_lines: list[str] | None = None
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
    if output_format == "json":
        rendered = json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n"
    else:
        rendered = render_process_report_markdown(report_payload, diff_lines=diff_lines)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"process improvement report written: {output.as_posix()}")

    if summary_file is not None:
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        with summary_file.open("a", encoding="utf-8") as handle:
            if output_format == "json":
                handle.write("Process improvement report JSON written to artifact.\n")
            else:
                handle.write(rendered + "\n")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a process-improvement report from task outcomes.")
    parser.add_argument("--task-outcomes-path", default=str(default_task_outcomes_path()))
    parser.add_argument("--output", default="process-improvement-report.md")
    parser.add_argument("--summary-file", default=None)
    parser.add_argument("--base-sha", default=None)
    parser.add_argument("--head-sha", default=None)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--weeks", type=int, default=8)
    parser.add_argument("--window-size", type=int, default=20)
    args = parser.parse_args()
    summary_path = Path(args.summary_file) if args.summary_file else None
    sys.exit(
        run(
            task_outcomes_path=Path(args.task_outcomes_path),
            output=Path(args.output),
            summary_file=summary_path,
            base_sha=args.base_sha,
            head_sha=args.head_sha,
            output_format=args.format,
            weeks=args.weeks,
            window_size=args.window_size,
        )
    )


if __name__ == "__main__":
    main()
