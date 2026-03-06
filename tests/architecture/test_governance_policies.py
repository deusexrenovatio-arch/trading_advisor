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


def test_validate_agent_contexts_passes() -> None:
    result = _run([sys.executable, "scripts/validate_agent_contexts.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_agent_memory_passes() -> None:
    result = _run([sys.executable, "scripts/validate_agent_memory.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_session_handoff_passes() -> None:
    result = _run([sys.executable, "scripts/validate_session_handoff.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_task_outcomes_passes() -> None:
    result = _run([sys.executable, "scripts/validate_task_outcomes.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_process_regressions_passes() -> None:
    result = _run([sys.executable, "scripts/validate_process_regressions.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_pr_only_policy_passes() -> None:
    result = _run([sys.executable, "scripts/validate_pr_only_policy.py"])
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


def test_autonomy_kpi_report_runs() -> None:
    output = ROOT / ".tmp/autonomy-kpi-architecture-smoke.md"
    result = _run([sys.executable, "scripts/autonomy_kpi_report.py", "--output", str(output)])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_flaky_policy_passes() -> None:
    result = _run([sys.executable, "scripts/validate_flaky_policy.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_codeowners_passes() -> None:
    result = _run([sys.executable, "scripts/validate_codeowners.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_taste_invariants_passes() -> None:
    result = _run([sys.executable, "scripts/validate_taste_invariants.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_python_style_passes() -> None:
    result = _run([sys.executable, "scripts/validate_python_style.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_structured_logging_passes() -> None:
    result = _run([sys.executable, "scripts/validate_structured_logging.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_observability_stack_passes() -> None:
    result = _run([sys.executable, "scripts/validate_observability_stack.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_governance_remediation_passes() -> None:
    result = _run([sys.executable, "scripts/validate_governance_remediation.py"])
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)


def test_validate_dependency_decisions_smoke_passes() -> None:
    result = _run(
        [
            sys.executable,
            "scripts/validate_dependency_decisions.py",
            "--base-sha",
            "HEAD",
            "--head-sha",
            "HEAD",
        ]
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + "\n" + result.stderr)
