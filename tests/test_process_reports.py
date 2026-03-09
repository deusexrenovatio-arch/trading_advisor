from __future__ import annotations

from moex_carry.governance.process_reports import build_process_report, render_process_report_markdown


def _record(index: int, **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "task_id": f"TASK-{index}",
        "closed_at": f"2026-03-0{1 + index}T10:00:00Z",
        "branch": "codex/process-reports-ui",
        "goal_class": "ops",
        "start_primary_context": "CTX-OPS",
        "start_contexts": ["CTX-OPS"],
        "final_contexts": ["CTX-OPS"],
        "route_match": "matched",
        "time_to_first_patch_sec": 45 + index,
        "same_path_attempts": 1,
        "decision_quality": "correct_first_time",
        "primary_rework_cause": "none",
        "incident_signature": "none",
        "improvement_action": "none",
        "improvement_artifact": "none",
        "linked_plan_id": None,
        "linked_memory_id": None,
        "outcome_status": "completed",
        "unmapped_files_count": 0,
        "intent_sources": ["session_handoff"],
        "start_recommendations": ["Patch is scoped to one context."],
    }
    record.update(overrides)
    return record


def test_build_process_report_includes_weekly_history_and_recommendation_signals() -> None:
    payload = {
        "items": [
            _record(0),
            _record(
                1,
                decision_quality="wrong_path",
                route_match="expanded",
                incident_signature="ctx.split",
                primary_rework_cause="context_gap",
                start_recommendations=[
                    "Patch touches multiple contexts. Split by ownership to keep review and agent context small."
                ],
            ),
            _record(
                2,
                decision_quality="environment_blocked",
                primary_rework_cause="environment",
                incident_signature="env.lock",
                start_recommendations=[
                    "Some files are unmapped. Classify manually before implementation."
                ],
            ),
        ]
    }

    report = build_process_report(payload, window_size=3, max_weeks=4)

    assert report["completed_tasks_count"] == 3
    assert report["current_rollup"]["top_start_recommendations"]
    assert report["current_rollup"]["high_risk_start_recommendations"]
    assert report["weekly_reports"]
    assert report["weekly_reports"][0]["human_summary"]["headline"]
    assert report["human_summary"]["what_to_change_next"]


def test_build_process_report_normalizes_missing_environment_signature() -> None:
    payload = {
        "items": [
            _record(
                0,
                decision_quality="environment_blocked",
                primary_rework_cause="environment",
                incident_signature="none",
            )
        ]
    }

    report = build_process_report(payload, window_size=1, max_weeks=1)

    assert report["current_rollup"]["top_environment_blockers"] == [("environment/no-signature", 1)]
    assert "none" not in report["human_summary"]["why_it_drifted"]
    assert "блокер среды без сигнатуры" in report["human_summary"]["why_it_drifted"]


def test_render_process_report_markdown_contains_human_summary_sections() -> None:
    payload = {"items": [_record(0), _record(1)]}
    report = build_process_report(payload, window_size=2, max_weeks=2)

    markdown = render_process_report_markdown(report)

    assert "## Human Summary" in markdown
    assert "## Weekly Reports" in markdown
    assert "Top Start Recommendations" in markdown
