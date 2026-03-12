from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


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
    outcome_status: str = "in_progress",
    decision_quality: str = "pending",
    final_contexts: str = "pending",
    route_match: str = "pending",
    primary_rework_cause: str = "none",
    incident_signature: str = "none",
    improvement_action: str = "pending",
    improvement_artifact: str = "pending",
    linked_plan_id: str | None = None,
    blockers: str = "None.",
) -> None:
    lines = [
        "# Session Handoff",
        "Updated: 2026-03-06 12:00 UTC",
        "",
        "## Goal",
        "- Validate task outcome sync and guards.",
        "",
        "## Task Request Contract",
        "- Objective: validate task outcome governance.",
        "- In Scope: telemetry and ledger.",
        "- Out of Scope: product logic.",
        "- Constraints: keep repo-local.",
        "- Done Evidence: pytest passes.",
        "- Priority Rule: correctness first.",
        "",
        "## Current Delta",
        "- Task outcome tests created in temp repo.",
        "",
        "## First-Time-Right Report",
        "1. Confirmed coverage: sync, validation, and diff-window gates.",
        "2. Missing or risky scenarios: powershell integration is optional.",
        "3. Resource/time risks and chosen controls: use temp git repos only.",
        "4. Highest-priority fixes or follow-ups: add more report assertions if needed.",
        "",
        "## Repetition Control",
        "- Max Same-Path Attempts: 2",
        "- Stop Trigger: two failed task-outcome edits.",
        "- Reset Action: inspect ledger and state.",
        "- New Search Space: sync, validation, diff refs.",
        "- Next Probe: run validator after sync.",
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
            f"- {blockers}",
            "",
            "## Next Step",
            "- Continue validation.",
            "",
            "## Validation",
            "- `pytest`",
            "",
        ]
    )
    handoff_path = repo_root / "docs/session_handoff.md"
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text("\n".join(lines), encoding="utf-8")


def _write_pointer_handoff_with_task_note(repo_root: Path) -> None:
    note_relative = "docs/tasks/active/TASK-2026-03-10-lean-harness-redesign.md"
    note_path = repo_root / note_relative
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_lines = [
        "# Task Note",
        "Updated: 2026-03-10 12:00 UTC",
        "",
        "## Goal",
        "- Validate task-note archive lifecycle on session closeout.",
        "",
        "## Task Request Contract",
        "- Objective: close the task and archive the note.",
        "- In Scope: task_session end lifecycle sync.",
        "- Out of Scope: product logic.",
        "- Constraints: stay repo-local.",
        "- Done Evidence: closeout commands pass.",
        "- Priority Rule: keep lifecycle deterministic.",
        "",
        "## Current Delta",
        "- Pointer handoff should move note to archive on closeout.",
        "",
        "## First-Time-Right Report",
        "1. Confirmed coverage: note path + index lifecycle.",
        "2. Missing or risky scenarios: stale index entries.",
        "3. Resource/time risks and chosen controls: minimal temp repo.",
        "4. Highest-priority fixes or follow-ups: index/archive sync.",
        "",
        "## Repetition Control",
        "- Max Same-Path Attempts: 2",
        "- Stop Trigger: lifecycle mismatch repeats twice.",
        "- Reset Action: inspect note/index sync.",
        "- New Search Space: pointer parsing, index update, archive move.",
        "- Next Probe: end session and assert archive state.",
        "",
        "## Task Outcome",
        "- Outcome Status: completed",
        "- Decision Quality: correct_first_time",
        "- Final Contexts: CTX-OPS",
        "- Route Match: matched",
        "- Primary Rework Cause: none",
        "- Incident Signature: none",
        "- Improvement Action: none",
        "- Improvement Artifact: none",
        "- Linked Plan ID: P1-TEMP-001",
        "",
        "## Blockers",
        "- No blocker.",
        "",
        "## Next Step",
        "- Run closeout.",
        "",
        "## Validation",
        "- `pytest`",
        "",
    ]
    note_path.write_text("\n".join(note_lines), encoding="utf-8")

    handoff_lines = [
        "# Session Handoff",
        "Updated: 2026-03-10 12:00 UTC",
        "",
        "## Active Task Note",
        f"- Path: {note_relative}",
        "- Mode: full",
        "- Status: in_progress",
        "",
        "## Validation",
        "- `pytest`",
        "",
    ]
    (repo_root / "docs/session_handoff.md").write_text("\n".join(handoff_lines), encoding="utf-8")

    active_index = {
        "version": 1,
        "updated_at": "2026-03-10",
        "items": [
            {
                "id": "TASK-2026-03-10-LEAN-HARNESS-REDESIGN",
                "path": note_relative,
                "mode": "full",
                "status": "in_progress",
                "started_at": "2026-03-10",
            }
        ],
    }
    archive_index = {
        "version": 1,
        "updated_at": "2026-03-10",
        "items": [],
    }
    active_index_path = repo_root / "docs/tasks/active/index.yaml"
    archive_index_path = repo_root / "docs/tasks/archive/index.yaml"
    active_index_path.parent.mkdir(parents=True, exist_ok=True)
    archive_index_path.parent.mkdir(parents=True, exist_ok=True)
    active_index_path.write_text(yaml.safe_dump(active_index, sort_keys=False), encoding="utf-8")
    archive_index_path.write_text(yaml.safe_dump(archive_index, sort_keys=False), encoding="utf-8")


def _init_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "scripts").mkdir()
    (repo_root / "memory").mkdir()
    (repo_root / "configs").mkdir()
    (repo_root / "configs/task_outcome_policy.yaml").write_text(
        (ROOT / "configs/task_outcome_policy.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo_root / "scripts/sample.py").write_text("print('baseline')\n", encoding="utf-8")
    (repo_root / "plans/PLANS.yaml").parent.mkdir(parents=True, exist_ok=True)
    (repo_root / "plans/PLANS.yaml").write_text(
        "version: 1\nupdated_at: 2026-03-06\nitems:\n- id: P1-TEMP-001\n  title: temp\n  lane: governance\n  status: active\n  execution_mode: autonomous\n  owner: test\n  acceptance:\n  - x\n  checks:\n  - pytest\n  docs:\n  - docs/session_handoff.md\n  dependencies: []\n  started_at: 2026-03-06\n",
        encoding="utf-8",
    )
    (repo_root / "configs/agent_incident_policy.yaml").write_text(
        "version: 1\nincident:\n  max_same_path_attempts: 2\n",
        encoding="utf-8",
    )
    _write_handoff(repo_root)
    assert _run(["git", "init"], repo_root).returncode == 0
    assert _run(["git", "config", "user.email", "test@example.com"], repo_root).returncode == 0
    assert _run(["git", "config", "user.name", "Test User"], repo_root).returncode == 0
    assert _run(["git", "add", "."], repo_root).returncode == 0
    assert _run(["git", "commit", "-m", "init"], repo_root).returncode == 0
    return repo_root


def _copy_scripts(repo_root: Path, *names: str) -> None:
    scripts_dir = repo_root / "scripts"
    for name in names:
        scripts_dir.joinpath(name).write_text(
            (ROOT / "scripts" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def _write_minimal_change_surface_mapping(repo_root: Path) -> None:
    payload = {
        "version": 1,
        "surface_priority": ["governance", "docs-only"],
        "surfaces": {
            "governance": {
                "prefixes": ["scripts/", "docs/", "memory/", "plans/"],
            }
        },
        "docs_only": {
            "prefixes": ["docs/"],
            "suffixes": [".md"],
        },
        "command_profiles": {
            "loop": {"default": []},
            "pr": {"default": []},
            "nightly": {"default": []},
        },
    }
    (repo_root / "configs" / "change_surface_mapping.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def _task_state_path(repo_root: Path) -> Path:
    return repo_root / ".runlogs" / "agent-process" / "state.json"


def _session_lock_path(repo_root: Path) -> Path:
    return repo_root / ".runlogs" / "task-session" / "session-lock.json"


def test_task_session_begin_creates_lock_and_active_task(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    _copy_scripts(
        repo_root,
        "agent_process_telemetry.py",
        "context_router.py",
        "handoff_resolver.py",
        "task_session.py",
    )

    result = _run(
        [sys.executable, "scripts/task_session.py", "begin", "--request", "Validate session contract"],
        repo_root,
    )

    assert result.returncode == 0
    assert "task session: started" in result.stdout
    assert _session_lock_path(repo_root).exists()
    assert _task_state_path(repo_root).exists()

    lock_payload = json.loads(_session_lock_path(repo_root).read_text(encoding="utf-8"))
    state = telemetry.load_state(_task_state_path(repo_root))
    assert lock_payload["branch"]
    assert state["active_task"]["task_id"]
    assert state["active_task"]["first_patch_at"] is None


def test_run_loop_gate_requires_active_session(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    _copy_scripts(
        repo_root,
        "agent_process_telemetry.py",
        "compute_change_surface.py",
        "gate_common.py",
        "run_loop_gate.py",
        "task_session.py",
    )
    _write_minimal_change_surface_mapping(repo_root)
    (repo_root / "scripts" / "sample.py").write_text("print('changed without session')\n", encoding="utf-8")

    result = _run(
        [sys.executable, "scripts/run_loop_gate.py", "--from-git", "--git-ref", "HEAD"],
        repo_root,
    )

    assert result.returncode == 1
    assert "task_session.py begin" in result.stdout


def test_run_loop_gate_records_first_patch_after_begin(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    _copy_scripts(
        repo_root,
        "agent_process_telemetry.py",
        "compute_change_surface.py",
        "context_router.py",
        "gate_common.py",
        "handoff_resolver.py",
        "run_loop_gate.py",
        "task_session.py",
    )
    _write_minimal_change_surface_mapping(repo_root)

    begin_result = _run(
        [sys.executable, "scripts/task_session.py", "begin", "--request", "Record first patch"],
        repo_root,
    )
    assert begin_result.returncode == 0

    (repo_root / "scripts" / "sample.py").write_text("print('first real patch')\n", encoding="utf-8")
    loop_result = _run(
        [sys.executable, "scripts/run_loop_gate.py", "--from-git", "--git-ref", "HEAD"],
        repo_root,
    )

    assert loop_result.returncode == 0
    state = telemetry.load_state(_task_state_path(repo_root))
    assert state["active_task"]["first_patch_at"] is not None


def test_task_session_end_syncs_outcome_and_clears_lock(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    _copy_scripts(
        repo_root,
        "agent_process_telemetry.py",
        "context_router.py",
        "handoff_resolver.py",
        "sync_task_outcomes.py",
        "task_session.py",
    )

    begin_result = _run(
        [sys.executable, "scripts/task_session.py", "begin", "--request", "Close task cleanly"],
        repo_root,
    )
    assert begin_result.returncode == 0

    _write_handoff(
        repo_root,
        outcome_status="completed",
        decision_quality="correct_first_time",
        final_contexts="CTX-OPS",
        route_match="matched",
        improvement_action="none",
        improvement_artifact="none",
        linked_plan_id="P1-TEMP-001",
    )

    end_result = _run([sys.executable, "scripts/task_session.py", "end"], repo_root)

    assert end_result.returncode == 0
    assert not _session_lock_path(repo_root).exists()

    task_outcomes_path = repo_root / "memory" / "task_outcomes.yaml"
    payload = yaml.safe_load(task_outcomes_path.read_text(encoding="utf-8")) or {}
    assert payload["items"][0]["outcome_status"] == "completed"
    assert payload["items"][0]["closed_at"] is not None


def test_task_session_end_archives_task_note_and_indexes(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    _copy_scripts(
        repo_root,
        "agent_process_telemetry.py",
        "context_router.py",
        "handoff_resolver.py",
        "sync_task_outcomes.py",
        "task_session.py",
    )
    _write_pointer_handoff_with_task_note(repo_root)

    begin_result = _run(
        [sys.executable, "scripts/task_session.py", "begin", "--request", "Close pointer task note"],
        repo_root,
    )
    assert begin_result.returncode == 0

    end_result = _run([sys.executable, "scripts/task_session.py", "end"], repo_root)
    assert end_result.returncode == 0

    archived_note = repo_root / "docs/tasks/archive/TASK-2026-03-10-lean-harness-redesign.md"
    active_note = repo_root / "docs/tasks/active/TASK-2026-03-10-lean-harness-redesign.md"
    assert archived_note.exists()
    assert not active_note.exists()

    active_index = yaml.safe_load((repo_root / "docs/tasks/active/index.yaml").read_text(encoding="utf-8")) or {}
    archive_index = yaml.safe_load((repo_root / "docs/tasks/archive/index.yaml").read_text(encoding="utf-8")) or {}
    active_paths = [str(item.get("path", "")) for item in active_index.get("items", []) if isinstance(item, dict)]
    archive_items = [item for item in archive_index.get("items", []) if isinstance(item, dict)]
    assert "docs/tasks/active/TASK-2026-03-10-lean-harness-redesign.md" not in active_paths
    assert any(
        str(item.get("path")) == "docs/tasks/archive/TASK-2026-03-10-lean-harness-redesign.md"
        and str(item.get("status")) == "completed"
        for item in archive_items
    )

    handoff_text = (repo_root / "docs/session_handoff.md").read_text(encoding="utf-8")
    assert "- Path: docs/tasks/archive/TASK-2026-03-10-lean-harness-redesign.md" in handoff_text
    assert "- Status: completed" in handoff_text
