from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_validate_plans_registry_passes() -> None:
    result = _run([sys.executable, "scripts/validate_plans.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_architecture_policy_passes() -> None:
    result = _run(
        [
            sys.executable,
            "scripts/validate_architecture_policy.py",
            "--policy",
            "tests/fixtures/architecture_policy_smoke.yaml",
        ]
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_agent_memory_passes() -> None:
    result = _run([sys.executable, "scripts/validate_agent_memory.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_quality_scorecards_smoke_passes() -> None:
    result = _run(
        [
            sys.executable,
            "scripts/validate_quality_scorecards.py",
            "--config",
            "tests/fixtures/quality_scorecards_smoke.yaml",
        ]
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)
