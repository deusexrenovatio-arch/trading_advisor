import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "skill_update_decision.py"


def _run_decision(tmp_path: Path, args: list[str]) -> dict:
    command = [sys.executable, str(SCRIPT_PATH), "--json", *args]
    result = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _write_skill(root: Path, name: str) -> Path:
    skill_dir = root / ".cursor" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        f"""---
name: {name}
description: Deterministic workflow for {name} scope.
---
""",
        encoding="utf-8",
    )
    return skill_file


def test_known_skill_edit_routes_to_update_existing(tmp_path: Path) -> None:
    _write_skill(tmp_path, "ui-decision-log")

    payload = _run_decision(
        tmp_path,
        [
            "--skills-root",
            ".cursor/skills",
            "--changed-files",
            ".cursor/skills/ui-decision-log/SKILL.md",
        ],
    )

    assert payload["action"] == "UPDATE_EXISTING"
    assert payload["targets"][0]["name"] == "ui-decision-log"
    assert any(
        g["gate"] == "existing_skill_target" and g["status"] == "pass"
        for g in payload["gates"]
    )


def test_unknown_skill_path_routes_to_add_new(tmp_path: Path) -> None:
    _write_skill(tmp_path, "risk-profile-gates")

    payload = _run_decision(
        tmp_path,
        [
            "--skills-root",
            ".cursor/skills",
            "--changed-files",
            ".cursor/skills/new-skill/SKILL.md",
            "--request",
            "introduce experimental recurring issue review for new area",
        ],
    )

    assert payload["action"] == "ADD_NEW"
    assert payload["targets"][0]["name"] == "new-skill"
    assert any(g["gate"] == "existing_skill_target" for g in payload["gates"])
    assert any("skill-creator" in step for step in payload["next_steps"])


def test_no_inputs_returns_non_zero(tmp_path: Path) -> None:
    command = [
        sys.executable,
        str(SCRIPT_PATH),
    ]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1
