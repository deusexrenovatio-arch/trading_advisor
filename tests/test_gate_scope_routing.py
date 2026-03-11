from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_nightly_gate  # noqa: E402
import run_pr_gate  # noqa: E402


def _docs_surface(changed_files: list[str]) -> dict[str, object]:
    return {
        "mapping_path": "configs/change_surface_mapping.yaml",
        "changed_files": changed_files,
        "surfaces": ["docs-only"],
        "primary_surface": "docs-only",
        "docs_only": True,
        "surface_details": {"docs-only": changed_files},
        "commands": {
            "loop": [],
            "pr": ["python scripts/run_loop_gate.py"],
            "nightly": ["python scripts/run_pr_gate.py"],
        },
    }


def test_run_pr_gate_propagates_explicit_changed_files_to_loop(monkeypatch) -> None:
    captured: dict[str, str] = {}
    changed_files = ["docs/README.md"]

    monkeypatch.setattr(run_pr_gate, "collect_changed_files", lambda **_kwargs: changed_files)
    monkeypatch.setattr(
        run_pr_gate,
        "compute_surface",
        lambda _changed_files, mapping_path: _docs_surface(changed_files),
    )
    def _capture_loop_command(command: str) -> int:
        captured["command"] = command
        return 0

    monkeypatch.setattr(run_pr_gate, "run_command", _capture_loop_command)
    monkeypatch.setattr(run_pr_gate, "run_commands", lambda _commands: (0, None))
    monkeypatch.setattr(run_pr_gate, "write_summary", lambda **_kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_pr_gate.py", "--changed-files", "docs/README.md"],
    )

    assert run_pr_gate.main() == 0
    assert "--changed-files docs/README.md" in captured["command"]
    assert "--from-git" not in captured["command"]


def test_run_pr_gate_propagates_stdin_scope_to_loop(monkeypatch) -> None:
    captured: dict[str, str] = {}
    changed_files = ["docs/README.md", "docs/workflows/context-budget.md"]

    monkeypatch.setattr(run_pr_gate, "collect_changed_files", lambda **_kwargs: changed_files)
    monkeypatch.setattr(
        run_pr_gate,
        "compute_surface",
        lambda _changed_files, mapping_path: _docs_surface(changed_files),
    )
    def _capture_loop_command(command: str) -> int:
        captured["command"] = command
        return 0

    monkeypatch.setattr(run_pr_gate, "run_command", _capture_loop_command)
    monkeypatch.setattr(run_pr_gate, "run_commands", lambda _commands: (0, None))
    monkeypatch.setattr(run_pr_gate, "write_summary", lambda **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["run_pr_gate.py", "--stdin"])

    assert run_pr_gate.main() == 0
    assert "--changed-files docs/README.md docs/workflows/context-budget.md" in captured["command"]
    assert "--from-git" not in captured["command"]


def test_run_nightly_gate_propagates_explicit_changed_files_to_pr(monkeypatch) -> None:
    captured: dict[str, str] = {}
    changed_files = ["docs/README.md"]

    monkeypatch.setattr(run_nightly_gate, "collect_changed_files", lambda **_kwargs: changed_files)
    monkeypatch.setattr(
        run_nightly_gate,
        "compute_surface",
        lambda _changed_files, mapping_path: _docs_surface(changed_files),
    )
    def _capture_pr_command(command: str) -> int:
        captured["command"] = command
        return 0

    monkeypatch.setattr(run_nightly_gate, "run_command", _capture_pr_command)
    monkeypatch.setattr(run_nightly_gate, "run_commands", lambda _commands: (0, None))
    monkeypatch.setattr(run_nightly_gate, "write_summary", lambda **_kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_nightly_gate.py", "--changed-files", "docs/README.md"],
    )

    assert run_nightly_gate.main() == 0
    assert "--changed-files docs/README.md" in captured["command"]
    assert "--from-git" not in captured["command"]
