from __future__ import annotations

import argparse
import sys
from pathlib import Path


REQUIRED_SNIPPETS = [
    "| Principle | Check | Owner | CI Job |",
    "`python scripts/validate_plans.py`",
    "`python scripts/validate_session_handoff.py`",
    "`python scripts/validate_task_request_contract.py`",
    "`python scripts/validate_pr_only_policy.py`",
    "`python scripts/validate_architecture_policy.py`",
    "`python scripts/run_lean_gate.py`",
    "`python scripts/agent_review.py`",
    "`python scripts/doc_gardening_report.py`",
    "`python scripts/validate_quality_scorecards.py`",
    "`python scripts/self_heal.py`",
    "`python scripts/validate_agent_memory.py`",
    "`python scripts/autonomy_kpi_report.py`",
    "`python scripts/validate_dependency_decisions.py`",
    "`python scripts/validate_codeowners.py`",
    "`python scripts/validate_taste_invariants.py`",
    "`python scripts/validate_python_style.py`",
    "`python scripts/validate_structured_logging.py`",
    "`python scripts/validate_flaky_policy.py`",
    "`python scripts/validate_observability_stack.py`",
    "`python scripts/validate_governance_remediation.py`",
    "`python scripts/build_governance_dashboard.py`",
    "`spec_drift_count`",
    "`boundary_violations`",
    "`manual_scenarios_count`",
    "`unlinked_test_cases_count`",
    "`autonomous_completion_rate`",
]
REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"


def run(path: Path) -> int:
    if not path.exists():
        print(f"ERROR: harness guideline file not found: {path}", file=sys.stderr)
        print(f"remediation: see {REMEDIATION_DOC}", file=sys.stderr)
        return 1

    text = path.read_text(encoding="utf-8")
    missing = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in text]
    if missing:
        print("ERROR: harness guideline validation failed:", file=sys.stderr)
        for snippet in missing:
            print(f"- missing snippet: {snippet}", file=sys.stderr)
        print(f"remediation: see {REMEDIATION_DOC}", file=sys.stderr)
        return 1

    mapping_rows = [
        line for line in text.splitlines() if line.startswith("| ") and line.count("|") >= 5
    ]
    if len(mapping_rows) < 3:
        print(
            "ERROR: harness guideline mapping table looks incomplete (expected header + rows)",
            file=sys.stderr,
        )
        print(f"remediation: see {REMEDIATION_DOC}", file=sys.stderr)
        return 1

    print("harness guideline validation: OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate harness-guideline.md structure.")
    parser.add_argument("--path", default="harness-guideline.md")
    args = parser.parse_args()
    return run(Path(args.path))


if __name__ == "__main__":
    raise SystemExit(main())
