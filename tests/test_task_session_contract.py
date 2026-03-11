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
