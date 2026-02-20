from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

TODO_PATTERN = re.compile(r"\bTODO\b", re.IGNORECASE)
REQUIRED_DOCS = [
    Path("AGENTS.md"),
    Path("harness-guideline.md"),
    Path("docs/DEV_WORKFLOW.md"),
    Path("docs/checklists/first-time-right-gate.md"),
    Path("memory/agent_memory.yaml"),
    Path("plans/PLANS.yaml"),
]


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("YAML payload must be an object")
    return payload


def _count_todos(root: Path) -> int:
    count = 0
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        count += len(TODO_PATTERN.findall(text))
    return count


def _render_report(
    *,
    plans_age_days: int | None,
    todo_markers_count: int,
    missing_docs: list[str],
    warnings: list[str],
    errors: list[str],
) -> str:
    lines = [
        "# Docs Gardening Report",
        "",
        "| Indicator | Value |",
        "| --- | --- |",
        f"| `plans_age_days` | {plans_age_days if plans_age_days is not None else 'unknown'} |",
        f"| `todo_markers_count` | {todo_markers_count} |",
        f"| `missing_required_docs_count` | {len(missing_docs)} |",
        "",
    ]

    if missing_docs:
        lines.append("## Missing Required Docs")
        for item in missing_docs:
            lines.append(f"- {item}")
        lines.append("")

    if warnings:
        lines.append("## Warnings")
        for item in warnings:
            lines.append(f"- {item}")
        lines.append("")

    if errors:
        lines.append("## Errors")
        for item in errors:
            lines.append(f"- {item}")
        lines.append("")

    if not warnings and not errors:
        lines.append("Status: OK")
        lines.append("")
    return "\n".join(lines)


def run(*, plans_path: Path, docs_root: Path, output: Path, summary_file: Path | None) -> int:
    warnings: list[str] = []
    errors: list[str] = []

    missing_docs = [doc.as_posix() for doc in REQUIRED_DOCS if not doc.exists()]
    if missing_docs:
        errors.append("required source-of-truth docs are missing")

    plans_age_days: int | None = None
    if not plans_path.exists():
        errors.append(f"plans file missing: {plans_path.as_posix()}")
    else:
        try:
            plans = _load_yaml(plans_path)
            updated_at = str(plans.get("updated_at", "")).strip()
            if not updated_at:
                errors.append("plans file missing 'updated_at'")
            else:
                updated_date = date.fromisoformat(updated_at)
                plans_age_days = (date.today() - updated_date).days
                if plans_age_days > 30:
                    errors.append(f"plans registry is stale ({plans_age_days} days > 30)")
                elif plans_age_days > 14:
                    warnings.append(f"plans registry should be refreshed ({plans_age_days} days > 14)")
        except Exception as exc:
            errors.append(f"failed to read plans file: {exc}")

    todo_markers_count = _count_todos(docs_root)
    if todo_markers_count > 20:
        warnings.append(f"TODO markers count is high ({todo_markers_count})")

    report = _render_report(
        plans_age_days=plans_age_days,
        todo_markers_count=todo_markers_count,
        missing_docs=missing_docs,
        warnings=warnings,
        errors=errors,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"docs gardening report written: {output.as_posix()}")

    if summary_file is not None:
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        with summary_file.open("a", encoding="utf-8") as handle:
            handle.write(report + "\n")

    if errors:
        print("docs gardening: FAILED")
        return 1
    print("docs gardening: OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate docs gardening/entropy report.")
    parser.add_argument("--plans", default="plans/PLANS.yaml")
    parser.add_argument("--docs-root", default="docs")
    parser.add_argument("--output", default="docs-gardening-report.md")
    parser.add_argument("--summary-file", default=None)
    args = parser.parse_args()

    summary = Path(args.summary_file) if args.summary_file else None
    sys.exit(
        run(
            plans_path=Path(args.plans),
            docs_root=Path(args.docs_root),
            output=Path(args.output),
            summary_file=summary,
        )
    )


if __name__ == "__main__":
    main()
