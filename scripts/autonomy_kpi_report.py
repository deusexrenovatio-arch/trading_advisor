from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from agent_process_telemetry import compute_process_rollup, load_task_outcomes


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML payload must be object: {path}")
    return payload


def _safe_ratio(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _compute_plan_metrics(path: Path) -> dict[str, float | int]:
    plans = _load_yaml(path)
    rows = plans.get("items") or []
    if not isinstance(rows, list):
        rows = []

    total = 0
    completed = 0
    autonomous_completed = 0
    cycle_days_values: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        total += 1
        status = str(row.get("status", "")).strip()
        execution_mode = str(row.get("execution_mode", "")).strip()
        if status == "completed":
            completed += 1
            if execution_mode == "autonomous":
                autonomous_completed += 1
            started_at = str(row.get("started_at", "")).strip()
            completed_at = str(row.get("completed_at", "")).strip()
            if started_at and completed_at:
                start = date.fromisoformat(started_at)
                done = date.fromisoformat(completed_at)
                cycle_days_values.append(max((done - start).days, 0))

    mean_cycle_days = (
        sum(cycle_days_values) / len(cycle_days_values) if cycle_days_values else 0.0
    )
    return {
        "plan_items_total": total,
        "plan_items_completed": completed,
        "autonomous_items_completed": autonomous_completed,
        "autonomous_completion_rate": _safe_ratio(autonomous_completed, completed),
        "mean_cycle_time_days": mean_cycle_days,
    }


def _compute_memory_metrics(path: Path) -> dict[str, int]:
    payload = _load_yaml(path)
    decisions = payload.get("decisions") or []
    incidents = payload.get("incidents") or []
    patterns = payload.get("patterns") or []
    return {
        "memory_decisions_count": len(decisions) if isinstance(decisions, list) else 0,
        "memory_incidents_count": len(incidents) if isinstance(incidents, list) else 0,
        "memory_patterns_count": len(patterns) if isinstance(patterns, list) else 0,
    }


def _compute_quality_metrics(path: Path) -> dict[str, int]:
    payload = _load_yaml(path)
    dims = payload.get("dimensions") or []
    if not isinstance(dims, list):
        dims = []
    return {
        "quality_dimensions_total": len(dims),
        "quality_blocking_dimensions": len(
            [row for row in dims if isinstance(row, dict) and float(row.get("threshold", 1.0)) >= 1.0]
        ),
    }


def _compute_self_heal_metrics(path: Path) -> dict[str, int]:
    return {"self_heal_workflow_enabled": 1 if path.exists() else 0}


def _compute_process_metrics(path: Path) -> dict[str, float | int]:
    payload = load_task_outcomes(path)
    rollup = compute_process_rollup(payload)
    metrics = rollup["current_metrics"]
    return {
        "process_tasks_completed": rollup["completed_tasks_count"],
        "process_burn_in_complete": 1 if rollup["burn_in_complete"] else 0,
        "process_correct_first_time_pct": float(metrics.get("correct_first_time_pct", 0.0)),
        "process_start_match_pct": float(metrics.get("start_match_pct", 0.0)),
        "process_repeat_error_rate": float(metrics.get("repeat_error_rate", 0.0)),
        "process_environment_blocker_rate": float(metrics.get("environment_blocker_rate", 0.0)),
    }


def _render_report(metrics: dict[str, float | int]) -> str:
    lines = [
        "# Autonomy KPI Report",
        "",
        f"- generated_at: {date.today().isoformat()}",
        "",
        "| KPI | Value |",
        "| --- | --- |",
    ]
    ordered = [
        "plan_items_total",
        "plan_items_completed",
        "autonomous_items_completed",
        "autonomous_completion_rate",
        "mean_cycle_time_days",
        "memory_decisions_count",
        "memory_incidents_count",
        "memory_patterns_count",
        "quality_dimensions_total",
        "quality_blocking_dimensions",
        "self_heal_workflow_enabled",
        "process_tasks_completed",
        "process_burn_in_complete",
        "process_correct_first_time_pct",
        "process_start_match_pct",
        "process_repeat_error_rate",
        "process_environment_blocker_rate",
    ]
    for key in ordered:
        value = metrics.get(key, 0)
        if isinstance(value, float):
            lines.append(f"| `{key}` | {value:.2f} |")
        else:
            lines.append(f"| `{key}` | {value} |")
    lines.append("")
    return "\n".join(lines)


def run(
    *,
    plans_path: Path,
    memory_path: Path,
    quality_path: Path,
    task_outcomes_path: Path,
    self_heal_workflow_path: Path,
    output: Path,
    summary_file: Path | None,
) -> int:
    metrics: dict[str, float | int] = {}
    metrics.update(_compute_plan_metrics(plans_path))
    metrics.update(_compute_memory_metrics(memory_path))
    metrics.update(_compute_quality_metrics(quality_path))
    metrics.update(_compute_process_metrics(task_outcomes_path))
    metrics.update(_compute_self_heal_metrics(self_heal_workflow_path))

    report = _render_report(metrics)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"autonomy KPI report written: {output.as_posix()}")

    if summary_file is not None:
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        with summary_file.open("a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate autonomy KPI report from repository state.")
    parser.add_argument("--plans", default="plans/PLANS.yaml")
    parser.add_argument("--memory", default="memory/agent_memory.yaml")
    parser.add_argument("--quality-scorecards", default="configs/quality_scorecards.yaml")
    parser.add_argument("--task-outcomes", default="memory/task_outcomes.yaml")
    parser.add_argument("--self-heal-workflow", default=".github/workflows/self-heal.yml")
    parser.add_argument("--output", default="autonomy-kpi-report.md")
    parser.add_argument("--summary-file", default=None)
    args = parser.parse_args()
    summary = Path(args.summary_file) if args.summary_file else None
    raise SystemExit(
        run(
            plans_path=Path(args.plans),
            memory_path=Path(args.memory),
            quality_path=Path(args.quality_scorecards),
            task_outcomes_path=Path(args.task_outcomes),
            self_heal_workflow_path=Path(args.self_heal_workflow),
            output=Path(args.output),
            summary_file=summary,
        )
    )


if __name__ == "__main__":
    main()
