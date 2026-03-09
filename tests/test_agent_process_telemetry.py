from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_process_telemetry as telemetry  # noqa: E402


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


def _init_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "scripts").mkdir()
    (repo_root / "configs").mkdir()
    (repo_root / "configs/task_outcome_policy.yaml").write_text(
        (ROOT / "configs/task_outcome_policy.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo_root / "scripts/sample.py").write_text("print('baseline')\n", encoding="utf-8")
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


def _task_snapshot(
    *,
    task_id: str,
    branch: str,
    worktree_path: Path,
    started_at: str,
    outcome_status: str = "in_progress",
    closed_at: str | None = None,
) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "task_id": task_id,
        "task_key": f"{task_id.lower()}-key",
        "started_at": started_at,
        "branch": branch,
        "head_sha": "deadbeef",
        "scope_id": worktree_path.resolve().as_posix().lower(),
        "worktree_path": str(worktree_path.resolve()),
        "start_primary_context": "CTX-OPS",
        "start_contexts": ["CTX-OPS"],
        "intent_sources": ["session_handoff"],
        "unmapped_files_count": 0,
        "start_recommendations": ["No diff yet. Using request/session intent fallback."],
        "baseline_changed_files": [],
        "baseline_diff_hash": "base",
        "last_seen_diff_hash": "base",
        "last_path_signature": "",
        "current_same_path_attempts": 0,
        "max_same_path_attempts_observed": 0,
        "first_patch_at": None,
        "time_to_first_patch_sec": None,
        "first_patch_changed_files_count": 0,
        "first_patch_changed_contexts": [],
        "closed_at": closed_at,
        "outcome_status": outcome_status,
        "decision_quality": "pending" if outcome_status == "in_progress" else "correct_first_time",
        "route_match": "pending" if outcome_status == "in_progress" else "matched",
        "primary_rework_cause": "none",
        "incident_signature": "none",
        "improvement_action": "pending" if outcome_status == "in_progress" else "none",
        "improvement_artifact": "pending" if outcome_status == "in_progress" else "none",
    }
    if outcome_status != "in_progress":
        snapshot["final_contexts"] = ["CTX-OPS"]
    return snapshot


def _legacy_task_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    legacy = dict(snapshot)
    legacy.pop("scope_id", None)
    legacy.pop("worktree_path", None)
    return legacy


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


def test_rollup_respects_burn_in_and_thresholds() -> None:
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
    assert weak_rollup["threshold_results"]["decision-quality"]["ok"] is False
    assert weak_rollup["threshold_results"]["context-efficiency"]["ok"] is False
    assert weak_rollup["threshold_results"]["self-learning"]["ok"] is False


def test_start_task_in_linked_worktree_uses_shared_canonical_root(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    linked = tmp_path / "linked"
    assert _run(["git", "worktree", "add", "-b", "feat/linked", str(linked)], repo_root).returncode == 0

    monkeypatch.chdir(linked)
    events_path = telemetry.default_events_path()
    state_path = telemetry.default_state_path()
    handoff_path = linked / "docs/session_handoff.md"

    created, active = telemetry.start_task(
        events_path=events_path,
        state_path=state_path,
        handoff_path=handoff_path,
    )

    assert created is True
    assert active["worktree_path"] == str(linked.resolve())
    assert events_path == (repo_root / ".runlogs/agent-process/task-events.jsonl").resolve()
    assert state_path == (repo_root / ".runlogs/agent-process/state.json").resolve()
    assert events_path.exists()
    assert not (linked / ".runlogs/agent-process/task-events.jsonl").exists()


def test_reconcile_legacy_process_storage_merges_worktree_shards(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    linked = tmp_path / "linked"
    assert _run(["git", "worktree", "add", "-b", "feat/linked", str(linked)], repo_root).returncode == 0

    canonical_root = repo_root / ".runlogs/agent-process"
    canonical_events = canonical_root / "task-events.jsonl"
    canonical_state = canonical_root / "state.json"
    legacy_root = linked / ".runlogs/agent-process"
    legacy_events = legacy_root / "task-events.jsonl"
    legacy_state = legacy_root / "state.json"

    root_task = _task_snapshot(
        task_id="ROOT-1",
        branch="main",
        worktree_path=repo_root,
        started_at="2026-03-09T10:00:00Z",
    )
    linked_task = _task_snapshot(
        task_id="LINKED-1",
        branch="feat/linked",
        worktree_path=linked,
        started_at="2026-03-09T10:05:00Z",
        outcome_status="completed",
        closed_at="2026-03-09T10:07:00Z",
    )
    telemetry.write_json(canonical_state, {"version": 1, "active_task": _legacy_task_snapshot(root_task)})
    telemetry.append_jsonl(
        canonical_events,
        {"event_type": "task_start", "task_id": "ROOT-1", "started_at": "2026-03-09T10:00:00Z"},
    )
    telemetry.write_json(legacy_state, {"version": 1, "active_task": _legacy_task_snapshot(linked_task)})
    telemetry.append_jsonl(
        legacy_events,
        {"event_type": "task_start", "task_id": "LINKED-1", "started_at": "2026-03-09T10:05:00Z"},
    )

    state = telemetry.reconcile_legacy_process_storage(
        linked,
        events_path=canonical_events,
        state_path=canonical_state,
    )

    merged_events = _events(canonical_events)
    assert {event["task_id"] for event in merged_events} == {"ROOT-1", "LINKED-1"}
    assert telemetry.get_active_task(state, repo_root) is not None
    assert telemetry.get_active_task(state, repo_root)["task_id"] == "ROOT-1"
    assert telemetry.get_active_task(state, linked) is not None
    assert telemetry.get_active_task(state, linked)["task_id"] == "LINKED-1"
    assert "default" not in state["tasks_by_scope"]
    assert all(not key.endswith("/.runlogs") for key in state["tasks_by_scope"])

    persisted = telemetry.load_state(canonical_state)
    assert len(persisted["tasks_by_scope"]) == 2
    assert set(persisted["tasks_by_scope"]) == {
        repo_root.resolve().as_posix().lower(),
        linked.resolve().as_posix().lower(),
    }
    assert persisted["migration"]["canonical_worktree"] == str(repo_root.resolve())


def test_reconcile_legacy_process_storage_repairs_buggy_runlogs_scope(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    canonical_root = repo_root / ".runlogs/agent-process"
    canonical_state = canonical_root / "state.json"
    buggy_worktree_path = repo_root / ".runlogs"
    buggy_task = _task_snapshot(
        task_id="BUG-1",
        branch="main",
        worktree_path=buggy_worktree_path,
        started_at="2026-03-09T10:00:00Z",
    )
    telemetry.write_json(
        canonical_state,
        {
            "version": 2,
            "tasks_by_scope": {
                buggy_worktree_path.resolve().as_posix().lower(): buggy_task,
            },
            "active_task": buggy_task,
        },
    )

    state = telemetry.reconcile_legacy_process_storage(
        repo_root,
        events_path=canonical_root / "task-events.jsonl",
        state_path=canonical_state,
    )

    assert set(state["tasks_by_scope"]) == {repo_root.resolve().as_posix().lower()}
    repaired = telemetry.get_active_task(state, repo_root)
    assert repaired is not None
    assert repaired["task_id"] == "BUG-1"
    assert repaired["worktree_path"] == str(repo_root.resolve())
