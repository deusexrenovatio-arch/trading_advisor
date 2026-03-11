from __future__ import annotations

import argparse
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    "## `python scripts/task_session.py begin --request \"<request>\"`",
    "## `python scripts/task_session.py end`",
    "## `python scripts/run_loop_gate.py`",
    "## `python scripts/run_pr_gate.py`",
    "## `python scripts/validate_plans.py`",
    "## `python scripts/validate_agent_memory.py`",
    "## `python scripts/validate_session_handoff.py`",
    "## `python scripts/validate_task_request_contract.py`",
    "## `python scripts/validate_task_outcomes.py`",
    "## `python scripts/validate_process_regressions.py`",
    "## `python scripts/validate_pr_only_policy.py`",
    "## `python scripts/validate_dependency_decisions.py`",
    "## `python scripts/validate_taste_invariants.py`",
    "## `python scripts/validate_python_style.py`",
    "## `python scripts/validate_structured_logging.py`",
    "## `python scripts/validate_codeowners.py`",
    "## `python scripts/validate_flaky_policy.py`",
    "## `python scripts/validate_observability_stack.py`",
    "## `python scripts/validate_quality_scorecards.py`",
    "## `python scripts/process_improvement_report.py`",
    "## `python scripts/build_governance_dashboard.py`",
]


def run(path: Path) -> int:
    if not path.exists():
        print(f"governance remediation validation failed: missing {path.as_posix()}")
        return 1

    text = path.read_text(encoding="utf-8", errors="ignore")
    missing = [section for section in REQUIRED_SECTIONS if section not in text]
    if missing:
        print("governance remediation validation failed: missing required sections")
        for section in missing:
            print(f"- {section}")
        return 1

    print("governance remediation validation: OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate governance remediation runbook completeness.")
    parser.add_argument("--path", default="docs/runbooks/governance-remediation.md")
    args = parser.parse_args()
    sys.exit(run(Path(args.path)))


if __name__ == "__main__":
    main()
