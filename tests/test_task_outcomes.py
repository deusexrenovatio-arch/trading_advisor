from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_process_telemetry as telemetry  # noqa: E402
import sync_task_outcomes  # noqa: E402
import validate_task_outcomes  # noqa: E402


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


def test_validate_task_outcomes_requires_sync_for_non_trivial_diff(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    events_path = repo_root / ".runlogs/agent-process/task-events.jsonl"
    state_path = repo_root / ".runlogs/agent-process/state.json"
    handoff_path = repo_root / "docs/session_handoff.md"
    task_outcomes_path = repo_root / "memory/task_outcomes.yaml"
    telemetry.start_task(events_path=events_path, state_path=state_path, handoff_path=handoff_path)
    (repo_root / "scripts/sample.py").write_text("print('changed')\n", encoding="utf-8")
    telemetry.record_first_patch(events_path=events_path, state_path=state_path, handoff_path=handoff_path)

    assert (
        validate_task_outcomes.run(
            session_handoff_path=handoff_path,
            state_path=state_path,
            task_outcomes_path=task_outcomes_path,
            incident_policy_path=repo_root / "configs/agent_incident_policy.yaml",
            focus=None,
            base_sha=None,
            head_sha=None,
        )
        == 1
    )

    assert (
        sync_task_outcomes.run(
            session_handoff_path=handoff_path,
            state_path=state_path,
            events_path=events_path,
            task_outcomes_path=task_outcomes_path,
        )
        == 0
    )
    assert (
        validate_task_outcomes.run(
            session_handoff_path=handoff_path,
            state_path=state_path,
            task_outcomes_path=task_outcomes_path,
            incident_policy_path=repo_root / "configs/agent_incident_policy.yaml",
            focus=None,
            base_sha=None,
            head_sha=None,
        )
        == 0
    )


def test_validate_task_outcomes_blocks_repeated_signature_without_new_artifact(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    events_path = repo_root / ".runlogs/agent-process/task-events.jsonl"
    state_path = repo_root / ".runlogs/agent-process/state.json"
    handoff_path = repo_root / "docs/session_handoff.md"
    task_outcomes_path = repo_root / "memory/task_outcomes.yaml"
    telemetry.start_task(events_path=events_path, state_path=state_path, handoff_path=handoff_path)
    (repo_root / "scripts/sample.py").write_text("print('changed')\n", encoding="utf-8")
    telemetry.record_first_patch(events_path=events_path, state_path=state_path, handoff_path=handoff_path)

    task_outcomes_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "updated_at": "2026-03-06",
                "items": [
                    {
                        "task_id": "OLD-1",
                        "closed_at": "2026-03-06T12:00:00Z",
                        "branch": "feat/old",
                        "goal_class": "ops",
                        "start_primary_context": "CTX-OPS",
                        "start_contexts": ["CTX-OPS"],
                        "final_contexts": ["CTX-OPS"],
                        "route_match": "mismatched",
                        "time_to_first_patch_sec": 30,
                        "same_path_attempts": 2,
                        "decision_quality": "wrong_path",
                        "primary_rework_cause": "workflow_gap",
                        "incident_signature": "repeat.sig",
                        "improvement_action": "workflow",
                        "improvement_artifact": "docs/runbooks/old.md",
                        "linked_plan_id": "P1-OLD-001",
                        "linked_memory_id": None,
                        "outcome_status": "partial",
                        "unmapped_files_count": 0,
                        "intent_sources": ["session_handoff"],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _write_handoff(
        repo_root,
        outcome_status="partial",
        decision_quality="wrong_path",
        final_contexts="CTX-OPS",
        route_match="mismatched",
        primary_rework_cause="workflow_gap",
        incident_signature="repeat.sig",
        improvement_action="workflow",
        improvement_artifact="docs/runbooks/old.md",
        linked_plan_id="P1-TEMP-001",
    )

    assert (
        sync_task_outcomes.run(
            session_handoff_path=handoff_path,
            state_path=state_path,
            events_path=events_path,
            task_outcomes_path=task_outcomes_path,
        )
        == 0
    )
    assert (
        validate_task_outcomes.run(
            session_handoff_path=handoff_path,
            state_path=state_path,
            task_outcomes_path=task_outcomes_path,
            incident_policy_path=repo_root / "configs/agent_incident_policy.yaml",
            focus=None,
            base_sha=None,
            head_sha=None,
        )
        == 1
    )


def test_sync_task_outcomes_derives_status_from_policy(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    events_path = repo_root / ".runlogs/agent-process/task-events.jsonl"
    state_path = repo_root / ".runlogs/agent-process/state.json"
    handoff_path = repo_root / "docs/session_handoff.md"
    task_outcomes_path = repo_root / "memory/task_outcomes.yaml"
    telemetry.start_task(events_path=events_path, state_path=state_path, handoff_path=handoff_path)
    (repo_root / "scripts/sample.py").write_text("print('changed')\n", encoding="utf-8")
    telemetry.record_first_patch(events_path=events_path, state_path=state_path, handoff_path=handoff_path)
    _write_handoff(
        repo_root,
        outcome_status="completed",
        decision_quality="wrong_path",
        final_contexts="CTX-OPS",
        route_match="mismatched",
        primary_rework_cause="workflow_gap",
        improvement_action="workflow",
        improvement_artifact="docs/runbooks/new.md",
        linked_plan_id="P1-TEMP-001",
    )

    assert (
        sync_task_outcomes.run(
            session_handoff_path=handoff_path,
            state_path=state_path,
            events_path=events_path,
            task_outcomes_path=task_outcomes_path,
        )
        == 0
    )

    payload = yaml.safe_load(task_outcomes_path.read_text(encoding="utf-8")) or {}
    item = payload["items"][0]
    assert item["decision_quality"] == "wrong_path"
    assert item["outcome_status"] == "partial"
    assert item["closed_at"] is not None


def test_validate_task_outcomes_blocks_status_mismatch_against_policy(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    events_path = repo_root / ".runlogs/agent-process/task-events.jsonl"
    state_path = repo_root / ".runlogs/agent-process/state.json"
    handoff_path = repo_root / "docs/session_handoff.md"
    task_outcomes_path = repo_root / "memory/task_outcomes.yaml"
    telemetry.start_task(events_path=events_path, state_path=state_path, handoff_path=handoff_path)
    (repo_root / "scripts/sample.py").write_text("print('changed')\n", encoding="utf-8")
    telemetry.record_first_patch(events_path=events_path, state_path=state_path, handoff_path=handoff_path)
    _write_handoff(
        repo_root,
        outcome_status="completed",
        decision_quality="wrong_path",
        final_contexts="CTX-OPS",
        route_match="mismatched",
        primary_rework_cause="workflow_gap",
        improvement_action="workflow",
        improvement_artifact="docs/runbooks/new.md",
        linked_plan_id="P1-TEMP-001",
    )
    assert (
        sync_task_outcomes.run(
            session_handoff_path=handoff_path,
            state_path=state_path,
            events_path=events_path,
            task_outcomes_path=task_outcomes_path,
        )
        == 0
    )

    assert (
        validate_task_outcomes.run(
            session_handoff_path=handoff_path,
            state_path=state_path,
            task_outcomes_path=task_outcomes_path,
            incident_policy_path=repo_root / "configs/agent_incident_policy.yaml",
            focus=None,
            base_sha=None,
            head_sha=None,
        )
        == 1
    )


def test_sync_task_outcomes_blocks_environment_blocked_without_blockers(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    events_path = repo_root / ".runlogs/agent-process/task-events.jsonl"
    state_path = repo_root / ".runlogs/agent-process/state.json"
    handoff_path = repo_root / "docs/session_handoff.md"
    task_outcomes_path = repo_root / "memory/task_outcomes.yaml"
    telemetry.start_task(events_path=events_path, state_path=state_path, handoff_path=handoff_path)
    (repo_root / "scripts/sample.py").write_text("print('changed')\n", encoding="utf-8")
    telemetry.record_first_patch(events_path=events_path, state_path=state_path, handoff_path=handoff_path)
    _write_handoff(
        repo_root,
        outcome_status="blocked",
        decision_quality="environment_blocked",
        final_contexts="CTX-OPS",
        route_match="matched",
        primary_rework_cause="environment",
        improvement_action="env",
        improvement_artifact="docs/runbooks/env.md",
        linked_plan_id="P1-TEMP-001",
        blockers="None.",
    )

    assert (
        sync_task_outcomes.run(
            session_handoff_path=handoff_path,
            state_path=state_path,
            events_path=events_path,
            task_outcomes_path=task_outcomes_path,
        )
        == 1
    )


def test_validate_task_outcomes_accepts_blocked_status_with_explicit_blocker(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    events_path = repo_root / ".runlogs/agent-process/task-events.jsonl"
    state_path = repo_root / ".runlogs/agent-process/state.json"
    handoff_path = repo_root / "docs/session_handoff.md"
    task_outcomes_path = repo_root / "memory/task_outcomes.yaml"
    telemetry.start_task(events_path=events_path, state_path=state_path, handoff_path=handoff_path)
    (repo_root / "scripts/sample.py").write_text("print('changed')\n", encoding="utf-8")
    telemetry.record_first_patch(events_path=events_path, state_path=state_path, handoff_path=handoff_path)
    _write_handoff(
        repo_root,
        outcome_status="blocked",
        decision_quality="environment_blocked",
        final_contexts="CTX-OPS",
        route_match="matched",
        primary_rework_cause="environment",
        improvement_action="env",
        improvement_artifact="docs/runbooks/env.md",
        linked_plan_id="P1-TEMP-001",
        blockers="CI runner credential is unavailable.",
    )

    assert (
        sync_task_outcomes.run(
            session_handoff_path=handoff_path,
            state_path=state_path,
            events_path=events_path,
            task_outcomes_path=task_outcomes_path,
        )
        == 0
    )
    assert (
        validate_task_outcomes.run(
            session_handoff_path=handoff_path,
            state_path=state_path,
            task_outcomes_path=task_outcomes_path,
            incident_policy_path=repo_root / "configs/agent_incident_policy.yaml",
            focus=None,
            base_sha=None,
            head_sha=None,
        )
        == 0
    )


def test_validate_task_outcomes_blocks_non_trivial_pr_without_handoff_or_ledger_updates(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    (repo_root / "memory/task_outcomes.yaml").write_text(
        "version: 1\nupdated_at: 2026-03-06\nitems: []\n",
        encoding="utf-8",
    )
    assert _run(["git", "add", "."], repo_root).returncode == 0
    assert _run(["git", "commit", "-m", "baseline"], repo_root).returncode == 0
    base_sha = _run(["git", "rev-parse", "HEAD"], repo_root).stdout.strip()

    (repo_root / "scripts/sample.py").write_text("print('new diff without closeout')\n", encoding="utf-8")
    assert _run(["git", "add", "scripts/sample.py"], repo_root).returncode == 0
    assert _run(["git", "commit", "-m", "change"], repo_root).returncode == 0
    head_sha = _run(["git", "rev-parse", "HEAD"], repo_root).stdout.strip()

    result = _run(
        [
            sys.executable,
            str(ROOT / "scripts/validate_task_outcomes.py"),
            "--base-sha",
            base_sha,
            "--head-sha",
            head_sha,
            "--session-handoff-path",
            "docs/session_handoff.md",
            "--task-outcomes-path",
            "memory/task_outcomes.yaml",
            "--incident-policy-path",
            "configs/agent_incident_policy.yaml",
        ],
        repo_root,
    )
    assert result.returncode == 1


def test_worktree_guard_check_emits_start_event_when_powershell_available(tmp_path: Path) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        return

    repo_root = _init_repo(tmp_path)
    scripts_dir = repo_root / "scripts"
    for name in ("worktree_guard.ps1", "agent_process_telemetry.py", "context_router.py"):
        scripts_dir.joinpath(name).write_text((ROOT / "scripts" / name).read_text(encoding="utf-8"), encoding="utf-8")

    init_result = _run(
        [shell, "-ExecutionPolicy", "Bypass", "-File", "scripts/worktree_guard.ps1", "-Action", "Init"],
        repo_root,
    )
    assert init_result.returncode == 0
    check_result = _run(
        [shell, "-ExecutionPolicy", "Bypass", "-File", "scripts/worktree_guard.ps1", "-Action", "Check"],
        repo_root,
    )
    assert check_result.returncode == 0
    assert "task_id=" in check_result.stdout
    assert "root=" in check_result.stdout
    assert (repo_root / ".runlogs/agent-process/state.json").exists()


def test_run_lean_gate_records_first_patch_in_minimal_repo(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    monkeypatch.chdir(repo_root)
    scripts_dir = repo_root / "scripts"
    for name in (
        "agent_process_telemetry.py",
        "context_router.py",
        "run_lean_gate.py",
        "sync_task_outcomes.py",
        "validate_task_outcomes.py",
        "validate_process_regressions.py",
    ):
        scripts_dir.joinpath(name).write_text((ROOT / "scripts" / name).read_text(encoding="utf-8"), encoding="utf-8")
    for name in (
        "sync_architecture_map.py",
        "validate_plans.py",
        "validate_agent_memory.py",
        "validate_session_handoff.py",
        "validate_task_request_contract.py",
        "validate_harness_guideline.py",
        "validate_pr_only_policy.py",
        "validate_architecture_policy.py",
        "validate_agent_contexts.py",
        "validate_test_cases.py",
        "validate_user_needs_catalog.py",
        "validate_skills.py",
        "validate_codeowners.py",
        "validate_flaky_policy.py",
        "validate_observability_stack.py",
        "validate_taste_invariants.py",
        "validate_python_style.py",
        "validate_structured_logging.py",
        "validate_dependency_decisions.py",
        "validate_governance_remediation.py",
        "harness_baseline_metrics.py",
    ):
        scripts_dir.joinpath(name).write_text("print('ok')\n", encoding="utf-8")

    telemetry.start_task(
        events_path=repo_root / ".runlogs/agent-process/task-events.jsonl",
        state_path=repo_root / ".runlogs/agent-process/state.json",
        handoff_path=repo_root / "docs/session_handoff.md",
    )
    (repo_root / "scripts/sample.py").write_text("print('first patch via lean gate')\n", encoding="utf-8")
    result = _run([sys.executable, "scripts/run_lean_gate.py"], repo_root)
    assert result.returncode == 0
    state = telemetry.load_state(repo_root / ".runlogs/agent-process/state.json")
    assert state["active_task"]["first_patch_at"] is not None


def test_build_governance_dashboard_runs_in_minimal_repo(tmp_path: Path) -> None:
    repo_root = tmp_path / "dashboard-repo"
    repo_root.mkdir()
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir()
    scripts_dir.joinpath("build_governance_dashboard.py").write_text(
        (ROOT / "scripts/build_governance_dashboard.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    scripts_dir.joinpath("validate_quality_scorecards.py").write_text(
        "from pathlib import Path\nimport sys\n"
        "report = Path(sys.argv[sys.argv.index('--report') + 1])\n"
        "report.write_text('# Quality\\n', encoding='utf-8')\n"
        "print('quality scorecards: OK')\n",
        encoding="utf-8",
    )
    scripts_dir.joinpath("autonomy_kpi_report.py").write_text(
        "from pathlib import Path\nimport sys\n"
        "output = Path(sys.argv[sys.argv.index('--output') + 1])\n"
        "output.write_text('# KPI\\n', encoding='utf-8')\n"
        "print('autonomy KPI report written')\n",
        encoding="utf-8",
    )
    scripts_dir.joinpath("process_improvement_report.py").write_text(
        "from pathlib import Path\nimport sys\n"
        "output = Path(sys.argv[sys.argv.index('--output') + 1])\n"
        "output.write_text('# Process\\n', encoding='utf-8')\n"
        "print('process improvement report written')\n",
        encoding="utf-8",
    )
    scripts_dir.joinpath("doc_gardening_report.py").write_text(
        "from pathlib import Path\nimport sys\n"
        "output = Path(sys.argv[sys.argv.index('--output') + 1])\n"
        "output.write_text('# Docs\\n', encoding='utf-8')\n"
        "print('docs gardening report written')\n",
        encoding="utf-8",
    )
    scripts_dir.joinpath("agent_review.py").write_text(
        "from pathlib import Path\nimport sys\n"
        "output = Path(sys.argv[sys.argv.index('--output') + 1])\n"
        "output.write_text('# Findings\\n', encoding='utf-8')\n"
        "print('agent review report written')\n",
        encoding="utf-8",
    )
    scripts_dir.joinpath("harness_baseline_metrics.py").write_text(
        "print('spec_drift_count=0')\n"
        "print('boundary_violations=0')\n"
        "print('manual_scenarios_count=0')\n"
        "print('unlinked_test_cases_count=0')\n",
        encoding="utf-8",
    )
    result = _run(
        [
            sys.executable,
            "scripts/build_governance_dashboard.py",
            "--output",
            "governance-dashboard.md",
            "--artifacts-dir",
            ".runlogs/governance-dashboard",
        ],
        repo_root,
    )
    assert result.returncode == 0
    assert (repo_root / "governance-dashboard.md").exists()
    assert (repo_root / ".runlogs/governance-dashboard/process-improvement-report.md").exists()
    assert (repo_root / ".runlogs/governance-dashboard/process-improvement-report.json").exists()
