from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_process_telemetry as telemetry  # noqa: E402
import validate_process_regressions  # noqa: E402


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    return subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True, env=env)


def _write_handoff(
    repo_root: Path,
    *,
    objective: str = "Track process telemetry end to end.",
    outcome_status: str = "in_progress",
    decision_quality: str = "pending",
    final_contexts: str = "pending",
    route_match: str = "pending",
    primary_rework_cause: str = "none",
    incident_signature: str = "none",
    improvement_action: str = "pending",
    improvement_artifact: str = "pending",
    linked_plan_id: str | None = None,
) -> None:
    lines = [
        "# Session Handoff",
        "Updated: 2026-03-06 12:00 UTC",
        "",
        "## Goal",
        "- Validate agent process telemetry in a temp git repo.",
        "",
        "## Task Request Contract",
        f"- Objective: {objective}",
        "- In Scope: telemetry and task-outcome scripts.",
        "- Out of Scope: product runtime changes.",
        "- Constraints: keep repo-local and deterministic.",
        "- Done Evidence: pytest passes.",
        "- Priority Rule: correctness first.",
        "",
        "## Current Delta",
        "- Created temp repo scaffolding for telemetry tests.",
        "",
        "## First-Time-Right Report",
        "1. Confirmed coverage: telemetry lifecycle and ledger validation.",
        "2. Missing or risky scenarios: powershell may be unavailable in CI.",
        "3. Resource/time risks and chosen controls: use temp repo and small files.",
        "4. Highest-priority fixes or follow-ups: cover diff-based validation paths.",
        "",
        "## Repetition Control",
        "- Max Same-Path Attempts: 2",
        "- Stop Trigger: two failed telemetry edits on the same path.",
        "- Reset Action: inspect temp repo state before more edits.",
        "- New Search Space: lifecycle, sync, validation, reporting.",
        "- Next Probe: run one start/first-patch cycle.",
        "",
        "## Task Outcome",
        f"- Outcome Status: {outcome_status}",
        f"- Decision Quality: {decision_quality}",
        f"- Final Contexts: {final_contexts}",
        f"- Route Match: {route_match}",
        f"- Primary Rework Cause: {primary_rework_cause}",
        f"- Incident Signature: {incident_signature}",
        f"- Improvement Action: {improvement_action}",
        f"- Improvement Artifact: {improvement_artifact}",
    ]
    if linked_plan_id:
        lines.append(f"- Linked Plan ID: {linked_plan_id}")
    lines.extend(
        [
            "",
            "## Blockers",
            "- None.",
            "",
            "## Next Step",
            "- Continue telemetry validation.",
            "",
            "## Validation",
            "- `pytest`",
            "",
        ]
    )
    handoff_path = repo_root / "docs/session_handoff.md"
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text("\n".join(lines), encoding="utf-8")


def _init_repo(tmp_path: Path, *, include_remediation_plan: bool = False) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "scripts").mkdir()
    (repo_root / "memory").mkdir()
    (repo_root / "plans").mkdir()
    (repo_root / "scripts/sample.py").write_text("print('baseline')\n", encoding="utf-8")
    plan_lines = [
        "version: 1",
        "updated_at: 2026-03-06",
        "items:",
        "- id: P1-TEMP-001",
        "  title: temp",
        "  lane: governance",
        "  status: active",
        "  execution_mode: autonomous",
        "  owner: test",
        "  acceptance:",
        "  - x",
        "  checks:",
        "  - pytest",
        "  docs:",
        "  - docs/session_handoff.md",
        "  dependencies: []",
        "  started_at: 2026-03-06",
    ]
    if include_remediation_plan:
        plan_lines.extend(
            [
                "- id: P1-PROCESS-REG-GATE-063",
                "  title: staged process regression remediation",
                "  lane: governance",
                "  status: active",
                "  execution_mode: autonomous",
                "  owner: test",
                "  acceptance:",
                "  - x",
                "  checks:",
                "  - pytest",
                "  docs:",
                "  - docs/session_handoff.md",
                "  dependencies: []",
                "  started_at: 2026-03-06",
            ]
        )
    (repo_root / "plans/PLANS.yaml").write_text("\n".join(plan_lines) + "\n", encoding="utf-8")
    (repo_root / "memory/task_outcomes.yaml").write_text(
        "version: 1\nupdated_at: 2026-03-06\nitems: []\n",
        encoding="utf-8",
    )
    _write_handoff(repo_root)
    assert _run(["git", "init"], repo_root).returncode == 0
    assert _run(["git", "config", "user.email", "test@example.com"], repo_root).returncode == 0
    assert _run(["git", "config", "user.name", "Test User"], repo_root).returncode == 0
    assert _run(["git", "add", "."], repo_root).returncode == 0
    assert _run(["git", "commit", "-m", "init"], repo_root).returncode == 0
    return repo_root


def _events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _build_record(index: int, **overrides: object) -> dict[str, object]:
    closed_at = (
        datetime(2026, 3, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
    ).isoformat().replace("+00:00", "Z")
    record: dict[str, object] = {
        "task_id": f"T-{index:02d}",
        "closed_at": closed_at,
        "branch": "feat/test",
        "goal_class": "ops",
        "start_primary_context": "CTX-OPS",
        "start_contexts": ["CTX-OPS"],
        "final_contexts": ["CTX-OPS"],
        "route_match": "matched",
        "time_to_first_patch_sec": 10 + index,
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


def test_start_task_deduplicates_and_restarts_on_contract_change(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    events_path = repo_root / ".runlogs/agent-process/task-events.jsonl"
    state_path = repo_root / ".runlogs/agent-process/state.json"
    handoff_path = repo_root / "docs/session_handoff.md"

    created, first = telemetry.start_task(
        events_path=events_path,
        state_path=state_path,
        handoff_path=handoff_path,
    )
    assert created is True
    assert first["start_primary_context"].startswith("CTX-")
    assert isinstance(first["start_recommendations"], list)
    assert first["start_recommendations"]
    assert len(_events(events_path)) == 1

    created_again, second = telemetry.start_task(
        events_path=events_path,
        state_path=state_path,
        handoff_path=handoff_path,
    )
    assert created_again is False
    assert second["task_id"] == first["task_id"]

    _write_handoff(repo_root, objective="Start a different telemetry task.")
    created_new, third = telemetry.start_task(
        events_path=events_path,
        state_path=state_path,
        handoff_path=handoff_path,
    )
    assert created_new is True
    assert third["task_id"] != first["task_id"]
    assert len(_events(events_path)) == 2


def test_first_patch_records_event_and_same_path_attempts(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    events_path = repo_root / ".runlogs/agent-process/task-events.jsonl"
    state_path = repo_root / ".runlogs/agent-process/state.json"
    handoff_path = repo_root / "docs/session_handoff.md"
    telemetry.start_task(events_path=events_path, state_path=state_path, handoff_path=handoff_path)

    target = repo_root / "scripts/sample.py"
    target.write_text("print('first change')\n", encoding="utf-8")
    recorded, active = telemetry.record_first_patch(
        events_path=events_path,
        state_path=state_path,
        handoff_path=handoff_path,
    )
    assert recorded is True
    assert active is not None
    assert active["time_to_first_patch_sec"] >= 0
    assert len(_events(events_path)) == 2

    target.write_text("print('second change same path')\n", encoding="utf-8")
    recorded_again, _ = telemetry.record_first_patch(
        events_path=events_path,
        state_path=state_path,
        handoff_path=handoff_path,
    )
    assert recorded_again is False
    state = telemetry.load_state(state_path)
    assert state["active_task"]["max_same_path_attempts_observed"] == 2


def test_rollup_respects_burn_in_and_thresholds(tmp_path: Path, monkeypatch) -> None:
    plan_path = tmp_path / "plans.yaml"
    plan_path.write_text("version: 1\nupdated_at: 2026-03-09\nitems: []\n", encoding="utf-8")
    monkeypatch.setenv("MOEX_CARRY_PLANS_PATH", str(plan_path))
    payload_under_burn_in = {"items": [_build_record(index) for index in range(19)]}
    rollup_under_burn_in = telemetry.compute_process_rollup(payload_under_burn_in)
    assert rollup_under_burn_in["burn_in_complete"] is False

    weak_payload = {
        "items": [
            _build_record(
                index,
                decision_quality="wrong_path" if index < 8 else "correct_first_time",
                route_match="expanded" if index < 6 else "matched",
                incident_signature="repeat.sig" if index in {0, 1, 2, 3} else "none",
                primary_rework_cause="environment" if index < 5 else "none",
            )
            for index in range(20)
        ]
    }
    weak_rollup = telemetry.compute_process_rollup(weak_payload)
    assert weak_rollup["burn_in_complete"] is True
    assert weak_rollup["current_metrics"]["correct_first_time_pct"] == 0.60
    assert weak_rollup["threshold_results"]["decision-quality"]["status"] == "fail"
    assert weak_rollup["threshold_results"]["decision-quality"]["blocking"] is True
    assert weak_rollup["threshold_results"]["context-efficiency"]["status"] == "fail"
    assert weak_rollup["threshold_results"]["context-efficiency"]["blocking"] is True
    assert weak_rollup["threshold_results"]["self-learning"]["status"] == "fail"
    assert weak_rollup["threshold_results"]["self-learning"]["blocking"] is True


def test_validate_process_regressions_allows_acknowledged_baseline_debt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = _init_repo(tmp_path, include_remediation_plan=True)
    monkeypatch.chdir(repo_root)
    task_outcomes_path = repo_root / "memory/task_outcomes.yaml"
    payload = {
        "version": 1,
        "updated_at": "2026-03-09",
        "items": [
            _build_record(
                index,
                decision_quality="wrong_path" if index < 8 else "correct_first_time",
                route_match="expanded" if index < 6 else "matched",
            )
            for index in range(20)
        ],
    }
    task_outcomes_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    assert (
        validate_process_regressions.run(
            task_outcomes_path=task_outcomes_path,
            focus=None,
            report=None,
        )
        == 0
    )
    rollup = telemetry.compute_process_rollup(payload)
    assert rollup["threshold_results"]["decision-quality"]["status"] == "acknowledged_debt"
    assert rollup["threshold_results"]["decision-quality"]["blocking"] is False
    assert rollup["threshold_results"]["context-efficiency"]["status"] == "acknowledged_debt"
    assert rollup["threshold_results"]["context-efficiency"]["blocking"] is False


def test_validate_process_regressions_blocks_worsening_acknowledged_debt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = _init_repo(tmp_path, include_remediation_plan=True)
    monkeypatch.chdir(repo_root)
    task_outcomes_path = repo_root / "memory/task_outcomes.yaml"
    previous_window = [
        _build_record(
            index,
            decision_quality="wrong_path" if index < 7 else "correct_first_time",
            route_match="expanded" if index < 6 else "matched",
        )
        for index in range(20)
    ]
    current_window = [
        _build_record(
            20 + index,
            decision_quality="wrong_path" if index < 8 else "correct_first_time",
            route_match="expanded" if index < 7 else "matched",
        )
        for index in range(20)
    ]
    payload = {
        "version": 1,
        "updated_at": "2026-03-09",
        "items": previous_window + current_window,
    }
    task_outcomes_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    assert (
        validate_process_regressions.run(
            task_outcomes_path=task_outcomes_path,
            focus=None,
            report=None,
        )
        == 1
    )
    rollup = telemetry.compute_process_rollup(payload)
    assert rollup["threshold_results"]["decision-quality"]["status"] == "regressed"
    assert rollup["threshold_results"]["decision-quality"]["blocking"] is True
    assert rollup["threshold_results"]["context-efficiency"]["status"] == "regressed"
    assert rollup["threshold_results"]["context-efficiency"]["blocking"] is True
