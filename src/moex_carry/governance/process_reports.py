from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

import yaml

from moex_carry.governance.process_report_text import (
    build_human_summary as _build_human_summary,
    normalize_environment_blocker_signature,
)


ROLLING_WINDOW_SIZE = 20
ROLLING_THRESHOLDS = {
    "decision-quality": {
        "correct_first_time_pct": ("ge", 0.70),
    },
    "context-efficiency": {
        "start_match_pct": ("ge", 0.75),
        "context_expansion_rate": ("le", 0.25),
    },
    "self-learning": {
        "repeat_error_rate": ("le", 0.15),
        "environment_blocker_rate": ("le", 0.20),
    },
}

KEY_WEEKLY_METRICS = (
    "correct_first_time_pct",
    "start_match_pct",
    "context_expansion_rate",
    "repeat_error_rate",
    "environment_blocker_rate",
    "median_time_to_first_patch_sec",
)

def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _safe_ratio(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _percentile(values: list[int], percentile_value: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    raw_index = percentile_value * (len(ordered) - 1)
    lower = int(raw_index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = raw_index - lower
    return int(round(ordered[lower] * (1 - weight) + ordered[upper] * weight))


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML object in {path.as_posix()}")
    return payload


def load_task_outcomes(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "updated_at": date.today().isoformat(), "items": []}
    payload = _load_yaml(path)
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    return {
        "version": payload.get("version", 1),
        "updated_at": str(payload.get("updated_at", date.today().isoformat())),
        "items": items,
    }


def _normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    start_recommendations = raw.get("start_recommendations", [])
    if not isinstance(start_recommendations, list):
        start_recommendations = []
    return {
        "task_id": str(raw.get("task_id", "")).strip(),
        "closed_at": raw.get("closed_at"),
        "branch": str(raw.get("branch", "")).strip(),
        "goal_class": str(raw.get("goal_class", "unknown")).strip() or "unknown",
        "start_primary_context": str(raw.get("start_primary_context", "unknown")).strip() or "unknown",
        "start_contexts": [str(item).strip() for item in raw.get("start_contexts", []) if str(item).strip()],
        "final_contexts": [str(item).strip() for item in raw.get("final_contexts", []) if str(item).strip()],
        "route_match": str(raw.get("route_match", "pending")).strip().lower() or "pending",
        "time_to_first_patch_sec": raw.get("time_to_first_patch_sec"),
        "same_path_attempts": int(raw.get("same_path_attempts", 1) or 1),
        "decision_quality": str(raw.get("decision_quality", "pending")).strip().lower() or "pending",
        "primary_rework_cause": str(raw.get("primary_rework_cause", "none")).strip().lower() or "none",
        "incident_signature": str(raw.get("incident_signature", "none")).strip() or "none",
        "improvement_action": str(raw.get("improvement_action", "pending")).strip().lower() or "pending",
        "improvement_artifact": str(raw.get("improvement_artifact", "pending")).strip() or "pending",
        "linked_plan_id": str(raw.get("linked_plan_id", "")).strip() or None,
        "linked_memory_id": str(raw.get("linked_memory_id", "")).strip() or None,
        "outcome_status": str(raw.get("outcome_status", "in_progress")).strip().lower() or "in_progress",
        "unmapped_files_count": int(raw.get("unmapped_files_count", 0) or 0),
        "intent_sources": [str(item).strip() for item in raw.get("intent_sources", []) if str(item).strip()],
        "start_recommendations": [str(item).strip() for item in start_recommendations if str(item).strip()],
    }


def completed_task_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items", [])
    records: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        record = _normalize_record(raw)
        if record["outcome_status"] not in {"completed", "partial", "blocked"}:
            continue
        if not record.get("closed_at"):
            continue
        records.append(record)
    records.sort(
        key=lambda item: parse_iso_datetime(str(item.get("closed_at", "")))
        or datetime.min.replace(tzinfo=timezone.utc)
    )
    return records


def _decision_quality_by_goal_class(window: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in window:
        grouped[str(record.get("goal_class", "unknown"))].append(record)
    result: dict[str, dict[str, float | int]] = {}
    for goal_class, rows in sorted(grouped.items()):
        total = len(rows)
        result[goal_class] = {
            "tasks": total,
            "correct_first_time_pct": _safe_ratio(
                sum(1 for row in rows if row["decision_quality"] == "correct_first_time"),
                total,
            ),
            "correct_after_replan_pct": _safe_ratio(
                sum(1 for row in rows if row["decision_quality"] == "correct_after_replan"),
                total,
            ),
        }
    return result


def _enrich_repeat_markers(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_signatures: set[str] = set()
    enriched: list[dict[str, Any]] = []
    for record in records:
        clone = dict(record)
        signature = str(record.get("incident_signature", "")).strip()
        repeated = bool(signature and signature != "none" and signature in seen_signatures)
        clone["is_repeat_error"] = repeated
        if signature and signature != "none":
            seen_signatures.add(signature)
        enriched.append(clone)
    return enriched


def _is_problem_task(record: dict[str, Any]) -> bool:
    if record["decision_quality"] != "correct_first_time":
        return True
    if record["route_match"] != "matched":
        return True
    return record["outcome_status"] != "completed"


def compute_process_rollup(payload: dict[str, Any], window_size: int = ROLLING_WINDOW_SIZE) -> dict[str, Any]:
    completed = _enrich_repeat_markers(completed_task_records(payload))
    current_window = completed[-window_size:] if window_size > 0 else list(completed)
    previous_window = completed[-2 * window_size : -window_size] if window_size > 0 else []
    total = len(current_window)
    same_path_values = [int(row.get("same_path_attempts", 1) or 1) for row in current_window]
    timing_values = [
        int(row.get("time_to_first_patch_sec", 0) or 0)
        for row in current_window
        if row.get("time_to_first_patch_sec") is not None
    ]
    current_metrics = {
        "correct_first_time_pct": _safe_ratio(
            sum(1 for row in current_window if row["decision_quality"] == "correct_first_time"),
            total,
        ),
        "correct_after_replan_pct": _safe_ratio(
            sum(1 for row in current_window if row["decision_quality"] == "correct_after_replan"),
            total,
        ),
        "wrong_path_rate": _safe_ratio(
            sum(1 for row in current_window if row["decision_quality"] == "wrong_path"),
            total,
        ),
        "rework_rate": _safe_ratio(
            sum(1 for row in current_window if row["decision_quality"] != "correct_first_time"),
            total,
        ),
        "decision_quality_by_goal_class": _decision_quality_by_goal_class(current_window),
        "start_resolution_pct": _safe_ratio(
            sum(1 for row in current_window if row["start_primary_context"] not in {"", "unknown"}),
            total,
        ),
        "start_match_pct": _safe_ratio(
            sum(1 for row in current_window if row["route_match"] == "matched"),
            total,
        ),
        "single_context_task_pct": _safe_ratio(
            sum(1 for row in current_window if len(row["final_contexts"]) == 1),
            total,
        ),
        "context_expansion_rate": _safe_ratio(
            sum(
                1
                for row in current_window
                if row["route_match"] == "expanded"
                or len(row["final_contexts"]) > max(len(row["start_contexts"]), 1)
            ),
            total,
        ),
        "unmapped_significant_file_rate": _safe_ratio(
            sum(1 for row in current_window if int(row.get("unmapped_files_count", 0) or 0) > 0),
            total,
        ),
        "median_time_to_first_patch_sec": int(median(timing_values)) if timing_values else 0,
        "repeat_error_rate": _safe_ratio(
            sum(1 for row in current_window if row.get("is_repeat_error")),
            total,
        ),
        "environment_blocker_rate": _safe_ratio(
            sum(
                1
                for row in current_window
                if row["decision_quality"] == "environment_blocked"
                or row["primary_rework_cause"] == "environment"
            ),
            total,
        ),
        "same_path_attempts_p50": _percentile(same_path_values, 0.5),
        "same_path_attempts_p90": _percentile(same_path_values, 0.9),
    }

    previous_numeric_metrics: dict[str, float | int] = {}
    if previous_window:
        previous_rollup = compute_process_rollup({"items": previous_window}, window_size=len(previous_window))
        previous_numeric_metrics = previous_rollup["current_metrics"]

    deltas: dict[str, float | int] = {}
    for key, value in current_metrics.items():
        if isinstance(value, (int, float)) and key in previous_numeric_metrics and isinstance(
            previous_numeric_metrics[key], (int, float)
        ):
            deltas[key] = float(value) - float(previous_numeric_metrics[key])

    repeated_signatures = Counter(
        str(row["incident_signature"])
        for row in current_window
        if row.get("is_repeat_error") and row["incident_signature"] != "none"
    )
    signature_recurrence = Counter(
        str(row["incident_signature"])
        for row in current_window
        if row["incident_signature"] != "none"
    )
    environment_blockers = Counter(
        normalize_environment_blocker_signature(str(row.get("incident_signature", "")))
        for row in current_window
        if row["primary_rework_cause"] == "environment"
    )
    improvement_action_mix = Counter(
        str(row["improvement_action"])
        for row in current_window
        if row["improvement_action"] not in {"pending", ""}
    )
    recommendation_mix = Counter(
        recommendation
        for row in current_window
        for recommendation in row.get("start_recommendations", [])
    )
    high_risk_recommendations = Counter(
        recommendation
        for row in current_window
        if _is_problem_task(row)
        for recommendation in row.get("start_recommendations", [])
    )

    threshold_results: dict[str, dict[str, Any]] = {}
    burn_in_complete = len(completed) >= window_size
    for dimension, rules in ROLLING_THRESHOLDS.items():
        dimension_status = {"ok": True, "checks": []}
        for metric_name, (op_name, threshold) in rules.items():
            actual = float(current_metrics.get(metric_name, 0.0))
            passed = actual >= threshold if op_name == "ge" else actual <= threshold
            if not passed:
                dimension_status["ok"] = False
            dimension_status["checks"].append(
                {
                    "metric": metric_name,
                    "operator": op_name,
                    "threshold": threshold,
                    "actual": actual,
                    "passed": passed,
                }
            )
        threshold_results[dimension] = dimension_status

    return {
        "completed_tasks_count": len(completed),
        "window_size": window_size,
        "current_window_count": total,
        "burn_in_complete": burn_in_complete,
        "current_metrics": current_metrics,
        "previous_metrics": previous_numeric_metrics,
        "deltas": deltas,
        "top_repeated_error_signatures": repeated_signatures.most_common(5),
        "repeat_signature_recurrence": signature_recurrence.most_common(5),
        "top_environment_blockers": environment_blockers.most_common(5),
        "tasks_with_wrong_path_or_partial": [
            row
            for row in current_window
            if row["decision_quality"] == "wrong_path"
            or row["decision_quality"] == "partial_outcome"
            or row["outcome_status"] == "partial"
        ],
        "improvement_actions_without_followup": [
            row
            for row in current_window
            if row["improvement_action"] not in {"none", "pending"}
            and not row.get("linked_plan_id")
            and not row.get("linked_memory_id")
        ],
        "improvement_action_mix": dict(sorted(improvement_action_mix.items())),
        "top_start_recommendations": recommendation_mix.most_common(5),
        "high_risk_start_recommendations": high_risk_recommendations.most_common(5),
        "threshold_results": threshold_results,
    }


def _status_level(rollup: dict[str, Any]) -> str:
    if rollup["current_window_count"] == 0:
        return "empty"
    if not rollup["burn_in_complete"]:
        return "burn-in"
    failing_dimensions = [
        dimension for dimension, payload in rollup["threshold_results"].items() if not payload["ok"]
    ]
    if not failing_dimensions:
        return "healthy"
    if len(failing_dimensions) == 1:
        return "watch"
    return "critical"


def build_human_summary(rollup: dict[str, Any]) -> dict[str, Any]:
    status = _status_level(rollup)
    return _build_human_summary(rollup, status=status)


def _week_start(dt: datetime) -> date:
    normalized = dt.astimezone(timezone.utc).date()
    return normalized - timedelta(days=normalized.weekday())


def _build_weekly_reports(
    records: list[dict[str, Any]],
    *,
    max_weeks: int,
) -> list[dict[str, Any]]:
    grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        closed_at = parse_iso_datetime(str(record.get("closed_at", "")))
        if closed_at is None:
            continue
        grouped[_week_start(closed_at)].append(record)

    ordered_starts = sorted(grouped)
    if max_weeks > 0:
        ordered_starts = ordered_starts[-max_weeks:]

    weekly_reports: list[dict[str, Any]] = []
    previous_metrics: dict[str, float | int] | None = None
    for week_start in ordered_starts:
        week_records = grouped[week_start]
        week_payload = {"items": week_records}
        rollup = compute_process_rollup(week_payload, window_size=max(len(week_records), 1))
        metric_deltas: dict[str, float | int] = {}
        if previous_metrics is not None:
            for metric_name in KEY_WEEKLY_METRICS:
                current_value = rollup["current_metrics"].get(metric_name)
                previous_value = previous_metrics.get(metric_name)
                if isinstance(current_value, (int, float)) and isinstance(previous_value, (int, float)):
                    metric_deltas[metric_name] = float(current_value) - float(previous_value)
        weekly_reports.append(
            {
                "week_start": week_start.isoformat(),
                "week_end": (week_start + timedelta(days=6)).isoformat(),
                "week_label": f"Неделя от {week_start.isoformat()}",
                "tasks_count": len(week_records),
                "metrics": rollup["current_metrics"],
                "metric_deltas": metric_deltas,
                "top_repeated_error_signatures": rollup["top_repeated_error_signatures"],
                "top_environment_blockers": rollup["top_environment_blockers"],
                "top_start_recommendations": rollup["top_start_recommendations"],
                "high_risk_start_recommendations": rollup["high_risk_start_recommendations"],
                "tasks_of_note": [
                    {
                        "task_id": row["task_id"],
                        "decision_quality": row["decision_quality"],
                        "route_match": row["route_match"],
                        "outcome_status": row["outcome_status"],
                        "incident_signature": row["incident_signature"],
                        "start_recommendations": row.get("start_recommendations", []),
                    }
                    for row in week_records
                    if _is_problem_task(row)
                ][:5],
                "human_summary": build_human_summary(rollup),
            }
        )
        previous_metrics = rollup["current_metrics"]
    return weekly_reports


def build_process_report(
    payload: dict[str, Any],
    *,
    window_size: int = ROLLING_WINDOW_SIZE,
    max_weeks: int = 8,
) -> dict[str, Any]:
    records = completed_task_records(payload)
    current_rollup = compute_process_rollup(payload, window_size=window_size)
    weekly_reports = _build_weekly_reports(records, max_weeks=max_weeks)
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "completed_tasks_count": len(records),
        "rolling_window_size": window_size,
        "burn_in_complete": current_rollup["burn_in_complete"],
        "human_summary": build_human_summary(current_rollup),
        "current_rollup": current_rollup,
        "weekly_reports": list(reversed(weekly_reports)),
        "weekly_trend": weekly_reports,
    }


def render_rollup_markdown(rollup: dict[str, Any]) -> str:
    lines = [
        "# Process Improvement Rollup",
        "",
        f"- completed_tasks_count: {rollup['completed_tasks_count']}",
        f"- rolling_window_size: {rollup['window_size']}",
        f"- burn_in_complete: {rollup['burn_in_complete']}",
        "",
        "## Current Metrics",
        "",
        "| Metric | Value | Delta |",
        "| --- | --- | --- |",
    ]
    current_metrics = rollup["current_metrics"]
    deltas = rollup.get("deltas", {})
    for key, value in current_metrics.items():
        if isinstance(value, dict):
            continue
        if isinstance(value, float):
            value_text = f"{value:.2f}"
        else:
            value_text = str(value)
        delta_value = deltas.get(key)
        if isinstance(delta_value, float):
            delta_text = f"{delta_value:+.2f}"
        elif isinstance(delta_value, int):
            delta_text = f"{delta_value:+d}"
        else:
            delta_text = "n/a"
        lines.append(f"| `{key}` | {value_text} | {delta_text} |")

    lines.extend(
        [
            "",
            "## Thresholds",
            "",
            "| Dimension | Status | Checks |",
            "| --- | --- | --- |",
        ]
    )
    for dimension, payload in sorted(rollup["threshold_results"].items()):
        checks = ", ".join(
            f"{check['metric']} {check['operator']} {check['threshold']:.2f} (actual={check['actual']:.2f})"
            for check in payload["checks"]
        )
        status = "pass" if payload["ok"] or not rollup["burn_in_complete"] else "fail"
        if not rollup["burn_in_complete"]:
            status = "burn-in"
        lines.append(f"| `{dimension}` | {status} | {checks} |")

    def _append_ranked(title: str, items: list[tuple[str, int]]) -> None:
        lines.extend(["", f"## {title}", ""])
        if items:
            for name, count in items:
                lines.append(f"- `{name}`: {count}")
        else:
            lines.append("- none")

    _append_ranked("Top Repeated Error Signatures", list(rollup["top_repeated_error_signatures"]))
    _append_ranked("Repeat Signature Recurrence", list(rollup["repeat_signature_recurrence"]))
    _append_ranked("Top Environment Blockers", list(rollup["top_environment_blockers"]))
    _append_ranked("Top Start Recommendations", list(rollup["top_start_recommendations"]))
    _append_ranked("High-Risk Start Recommendations", list(rollup["high_risk_start_recommendations"]))

    lines.extend(["", "## Wrong Path Or Partial Tasks", ""])
    tasks = rollup["tasks_with_wrong_path_or_partial"]
    if tasks:
        for task in tasks:
            lines.append(
                "- "
                f"{task['task_id']} ({task['decision_quality']}, outcome={task['outcome_status']}, "
                f"route_match={task['route_match']})"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Improvement Actions Without Follow-Up", ""])
    missing = rollup["improvement_actions_without_followup"]
    if missing:
        for task in missing:
            lines.append(
                f"- {task['task_id']} action={task['improvement_action']} artifact={task['improvement_artifact']}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Improvement Action Mix", ""])
    mix = rollup["improvement_action_mix"]
    if mix:
        for name, count in sorted(mix.items()):
            lines.append(f"- `{name}`: {count}")
    else:
        lines.append("- none")

    return "\n".join(lines) + "\n"


def render_process_report_markdown(
    report: dict[str, Any],
    *,
    diff_lines: list[str] | None = None,
) -> str:
    current_rollup = report["current_rollup"]
    summary = report["human_summary"]
    lines = [
        "# Process Improvement Report",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- completed_tasks_count: {report['completed_tasks_count']}",
        f"- rolling_window_size: {report['rolling_window_size']}",
        f"- burn_in_complete: {report['burn_in_complete']}",
        "",
        "## Human Summary",
        "",
        f"- status: {summary['status']}",
        f"- headline: {summary['headline']}",
        f"- what_happened: {summary['what_happened']}",
        f"- why_it_drifted: {summary['why_it_drifted']}",
        "",
        "## What To Change Next",
        "",
    ]
    for item in summary["what_to_change_next"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Current Risks", ""])
    for item in summary["current_risks"]:
        lines.append(f"- {item}")

    lines.extend(["", render_rollup_markdown(current_rollup).rstrip(), "", "## Weekly Reports", ""])
    weekly_reports = report["weekly_reports"]
    if weekly_reports:
        for weekly in weekly_reports:
            weekly_summary = weekly["human_summary"]
            metrics = weekly["metrics"]
            lines.extend(
                [
                    f"### {weekly['week_label']}",
                    "",
                    f"- tasks_count: {weekly['tasks_count']}",
                    f"- correct_first_time_pct: {metrics['correct_first_time_pct']:.2f}",
                    f"- start_match_pct: {metrics['start_match_pct']:.2f}",
                    f"- repeat_error_rate: {metrics['repeat_error_rate']:.2f}",
                    f"- environment_blocker_rate: {metrics['environment_blocker_rate']:.2f}",
                    f"- headline: {weekly_summary['headline']}",
                    f"- why_it_drifted: {weekly_summary['why_it_drifted']}",
                    "",
                ]
            )
    else:
        lines.append("- none")

    if diff_lines:
        lines.extend(["", *diff_lines])

    return "\n".join(lines).rstrip() + "\n"
