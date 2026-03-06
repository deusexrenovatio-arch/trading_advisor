from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from agent_process_telemetry import load_task_outcomes


@dataclass(frozen=True)
class Finding:
    severity: str
    rule_id: str
    message: str
    recommendation: str


def _run_capture(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    return int(completed.returncode), completed.stdout.strip()


def _changed_files(base_sha: str | None, head_sha: str | None) -> list[str]:
    if base_sha and head_sha:
        code, out = _run_capture(["git", "diff", "--name-only", base_sha, head_sha])
    else:
        code, out = _run_capture(["git", "diff", "--name-only", "HEAD~1", "HEAD"])
    if code != 0:
        return []
    return sorted([line.strip() for line in out.splitlines() if line.strip()])


def _build_findings(changed: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    changed_set = set(changed)
    non_trivial = any(
        path not in {"docs/session_handoff.md", "memory/task_outcomes.yaml"} and not path.startswith(".runlogs/")
        for path in changed
    )

    src_changed = any(path.startswith("src/") for path in changed)
    tests_changed = any(path.startswith("tests/") or path.startswith("ui-web/tests/") for path in changed)
    if src_changed and not tests_changed:
        findings.append(
            Finding(
                severity="P1",
                rule_id="src-without-tests",
                message="Source code changed without test updates.",
                recommendation="Add or update regression tests for modified runtime behavior.",
            )
        )

    if "docs/contracts/api-v2.yaml" in changed_set:
        if "tests/test_api_v2.py" not in changed_set:
            findings.append(
                Finding(
                    severity="P1",
                    rule_id="api-contract-without-api-tests",
                    message="API contract changed without test_api_v2 update.",
                    recommendation="Update API v2 tests to cover contract changes.",
                )
            )
        if "src/moex_carry/ui/app.py" not in changed_set:
            findings.append(
                Finding(
                    severity="P2",
                    rule_id="api-contract-without-app-surface-change",
                    message="API contract changed but Flask route file was not updated in this diff.",
                    recommendation="Confirm change is docs-only; otherwise align app routes.",
                )
            )

    if any(path.startswith("scripts/validate_") for path in changed):
        governance_docs = {"docs/DEV_WORKFLOW.md", "harness-guideline.md", "AGENTS.md"}
        if not (changed_set & governance_docs):
            findings.append(
                Finding(
                    severity="P2",
                    rule_id="validator-without-governance-docs",
                    message="Validation scripts changed without governance docs update.",
                    recommendation="Document intent/rules in DEV_WORKFLOW or harness-guideline.",
                )
            )

    if "AGENTS.md" in changed_set and "docs/DEV_WORKFLOW.md" not in changed_set:
        findings.append(
            Finding(
                severity="P2",
                rule_id="agents-without-workflow-doc-sync",
                message="AGENTS.md changed without DEV_WORKFLOW sync in same diff.",
                recommendation="Verify process docs remain aligned to agent instructions.",
            )
        )

    if non_trivial:
        if "docs/session_handoff.md" not in changed_set:
            findings.append(
                Finding(
                    severity="P1",
                    rule_id="non-trivial-diff-without-task-outcome-handoff",
                    message="Non-trivial diff changed code/governance files without session handoff closeout update.",
                    recommendation="Update docs/session_handoff.md Task Outcome fields for the task.",
                )
            )
        if "memory/task_outcomes.yaml" not in changed_set:
            findings.append(
                Finding(
                    severity="P1",
                    rule_id="non-trivial-diff-without-task-outcome-ledger",
                    message="Non-trivial diff changed code/governance files without task outcomes ledger update.",
                    recommendation="Run scripts/sync_task_outcomes.py and commit memory/task_outcomes.yaml.",
                )
            )

    ledger = load_task_outcomes(Path("memory/task_outcomes.yaml"))
    repeated_without_followup = []
    seen_signatures: set[str] = set()
    for row in ledger.get("items", []):
        if not isinstance(row, dict):
            continue
        signature = str(row.get("incident_signature", "")).strip()
        if not signature or signature == "none":
            continue
        repeated = signature in seen_signatures
        seen_signatures.add(signature)
        if not repeated:
            continue
        action = str(row.get("improvement_action", "")).strip()
        artifact = str(row.get("improvement_artifact", "")).strip()
        linked_plan = str(row.get("linked_plan_id", "")).strip()
        linked_memory = str(row.get("linked_memory_id", "")).strip()
        if action in {"", "none", "pending"} or artifact in {"", "none", "pending"} or (not linked_plan and not linked_memory):
            repeated_without_followup.append(signature)
    if repeated_without_followup:
        findings.append(
            Finding(
                severity="P2",
                rule_id="repeated-signature-without-followup",
                message=(
                    "Repeated incident signatures exist without a distinct improvement artifact or linked follow-up: "
                    + ", ".join(sorted(set(repeated_without_followup)))
                ),
                recommendation="Add a new improvement artifact and linked plan/memory item for repeated signatures.",
            )
        )

    return findings


def _render_report(changed: list[str], findings: list[Finding]) -> str:
    lines = [
        "# Agent Review Findings",
        "",
        f"- changed_files_count: {len(changed)}",
        f"- findings_count: {len(findings)}",
        "",
    ]

    if changed:
        lines.append("## Changed Files")
        for path in changed:
            lines.append(f"- {path}")
        lines.append("")

    if findings:
        lines.extend(
            [
                "## Findings",
                "",
                "| Severity | Rule | Message | Recommendation |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in findings:
            lines.append(
                f"| {item.severity} | `{item.rule_id}` | {item.message} | {item.recommendation} |"
            )
        lines.append("")
    else:
        lines.append("## Findings")
        lines.append("- No findings.")
        lines.append("")

    return "\n".join(lines)


def run(
    *,
    base_sha: str | None,
    head_sha: str | None,
    output: Path,
    summary_file: Path | None,
) -> int:
    changed = _changed_files(base_sha, head_sha)
    findings = _build_findings(changed)
    report = _render_report(changed, findings)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"agent review report written: {output.as_posix()}")

    if summary_file is not None:
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        with summary_file.open("a", encoding="utf-8") as handle:
            handle.write(report + "\n")

    # P1/P2 are advisory; keep hard blocking for explicit P0 only.
    hard_fail = any(item.severity == "P0" for item in findings)
    if hard_fail:
        print("agent review: FAILED (P0 findings)")
        return 1

    print(f"agent review: OK (advisory_findings={len(findings)})")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic agent-review findings from diff.")
    parser.add_argument("--base-sha", default=None)
    parser.add_argument("--head-sha", default=None)
    parser.add_argument("--output", default="agent-review-findings.md")
    parser.add_argument("--summary-file", default=None)
    args = parser.parse_args()

    summary = Path(args.summary_file) if args.summary_file else None
    sys.exit(
        run(
            base_sha=args.base_sha,
            head_sha=args.head_sha,
            output=Path(args.output),
            summary_file=summary,
        )
    )


if __name__ == "__main__":
    main()
