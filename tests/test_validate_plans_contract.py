from __future__ import annotations

import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_plans  # noqa: E402


def _write_plan(
    repo_root: Path,
    *,
    status: str,
    check_command: str,
) -> Path:
    payload: dict[str, object] = {
        "version": 1,
        "updated_at": "2026-03-11",
        "items": [
            {
                "id": "P1-TEMP-PLAN-001",
                "title": "temp",
                "lane": "governance",
                "status": status,
                "execution_mode": "autonomous",
                "owner": "test",
                "acceptance": ["ok"],
                "checks": [check_command],
                "docs": ["docs/session_handoff.md"],
                "dependencies": [],
                "started_at": "2026-03-11",
            }
        ],
    }
    if status == "completed":
        item = payload["items"][0]
        assert isinstance(item, dict)
        item["completed_at"] = "2026-03-11"

    plan_path = repo_root / "plans" / "PLANS.yaml"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return plan_path


def test_validate_plans_rejects_missing_script_for_active_item(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plan_path = _write_plan(
        repo_root,
        status="active",
        check_command="python scripts/run_lean_gate.py",
    )

    assert validate_plans.run(plan_path) == 1


def test_validate_plans_allows_missing_script_for_completed_item(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plan_path = _write_plan(
        repo_root,
        status="completed",
        check_command="python scripts/run_lean_gate.py",
    )

    assert validate_plans.run(plan_path) == 0


def test_validate_plans_accepts_existing_script_for_active_item(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    script_path = repo_root / "scripts" / "run_loop_gate.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("print('ok')\n", encoding="utf-8")
    plan_path = _write_plan(
        repo_root,
        status="active",
        check_command="python scripts/run_loop_gate.py --skip-session-check",
    )

    assert validate_plans.run(plan_path) == 0
