from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_task_request_contract  # noqa: E402


def _write_incident_policy(repo_root: Path) -> None:
    policy = repo_root / "configs" / "agent_incident_policy.yaml"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        "version: 1\nincident:\n  max_same_path_attempts: 2\n",
        encoding="utf-8",
    )


def _write_task_note(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Task Note",
        "Updated: 2026-03-11 09:45 UTC",
        "",
        "## Task Request Contract",
        "- Objective: close governance tails.",
        "- In Scope: validators and policy docs.",
        "- Out of Scope: product features.",
        "- Constraints: deterministic closeout.",
        "- Done Evidence: focused tests pass.",
        "- Priority Rule: fail closed for governance.",
        "",
        "## First-Time-Right Report",
        "1. Confirmed coverage: all four findings are mapped.",
        "2. Missing or risky scenarios: historical completed items.",
        "3. Resource/time risks and chosen controls: scoped checks.",
        "4. Highest-priority fixes or follow-ups: pointer + plan checks.",
        "",
        "## Repetition Control",
        "- Max Same-Path Attempts: 2",
        "- Stop Trigger: repeated validator failure.",
        "- Reset Action: isolate fixture and retry.",
        "- New Search Space: pointer + scoped diff checks.",
        "- Next Probe: run targeted tests.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_handoff(path: Path, *, note_path: str, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Session Handoff",
        "Updated: 2026-03-11 09:45 UTC",
        "",
        "## Active Task Note",
        f"- Path: {note_path}",
        "- Mode: full",
        f"- Status: {status}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_validate_task_request_contract_blocks_archived_pointer_without_closeout_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.chdir(repo_root)
    _write_incident_policy(repo_root)
    archived_note = repo_root / "docs/tasks/archive/TASK-2026-03-10-closed.md"
    _write_task_note(archived_note)
    handoff_path = repo_root / "docs/session_handoff.md"
    _write_handoff(
        handoff_path,
        note_path="docs/tasks/archive/TASK-2026-03-10-closed.md",
        status="completed",
    )

    result = validate_task_request_contract.run(
        handoff_path,
        changed_files_override=["src/moex_carry/server/app.py"],
    )
    assert result == 1


def test_validate_task_request_contract_allows_archived_pointer_with_scoped_closeout_diff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.chdir(repo_root)
    _write_incident_policy(repo_root)
    archived_note = repo_root / "docs/tasks/archive/TASK-2026-03-10-closed.md"
    _write_task_note(archived_note)
    handoff_path = repo_root / "docs/session_handoff.md"
    _write_handoff(
        handoff_path,
        note_path="docs/tasks/archive/TASK-2026-03-10-closed.md",
        status="completed",
    )

    result = validate_task_request_contract.run(
        handoff_path,
        changed_files_override=[
            "docs/session_handoff.md",
            "docs/tasks/archive/TASK-2026-03-10-closed.md",
        ],
    )
    assert result == 0


def test_validate_task_request_contract_accepts_active_pointer(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.chdir(repo_root)
    _write_incident_policy(repo_root)
    active_note = repo_root / "docs/tasks/active/TASK-2026-03-11-current.md"
    _write_task_note(active_note)
    handoff_path = repo_root / "docs/session_handoff.md"
    _write_handoff(
        handoff_path,
        note_path="docs/tasks/active/TASK-2026-03-11-current.md",
        status="in_progress",
    )

    result = validate_task_request_contract.run(handoff_path)
    assert result == 0
