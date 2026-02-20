from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class ComponentResult:
    name: str
    artifact: Path
    returncode: int


def _run_capture(command: list[str]) -> tuple[int, str, str]:
    print(f">>> {' '.join(command)}", flush=True)
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    return int(completed.returncode), stdout, stderr


def _parse_metrics(output: str) -> dict[str, int]:
    metrics: dict[str, int] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key_text = key.strip()
        value_text = value.strip()
        if not key_text:
            continue
        try:
            metrics[key_text] = int(value_text)
        except ValueError:
            continue
    return metrics


def _render_dashboard(
    *,
    components: list[ComponentResult],
    metrics: dict[str, int],
) -> str:
    now_utc = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Governance Dashboard",
        "",
        f"- generated_at_utc: {now_utc}",
        "",
        "## Component Status",
        "",
        "| Component | Status | Artifact |",
        "| --- | --- | --- |",
    ]
    for result in components:
        status = "OK" if result.returncode == 0 else "FAILED"
        lines.append(
            f"| `{result.name}` | {status} | `{result.artifact.as_posix()}` |"
        )

    lines.extend(
        [
            "",
            "## Harness Baseline Metrics",
            "",
            "| Metric | Value |",
            "| --- | --- |",
        ]
    )
    for key in (
        "spec_drift_count",
        "boundary_violations",
        "manual_scenarios_count",
        "unlinked_test_cases_count",
    ):
        lines.append(f"| `{key}` | {metrics.get(key, 0)} |")

    lines.extend(
        [
            "",
            "## Included Reports",
            "",
        ]
    )
    for result in components:
        lines.append(f"- `{result.artifact.as_posix()}`")
    lines.append("")
    return "\n".join(lines)


def run(
    *,
    output: Path,
    artifacts_dir: Path,
    base_sha: str | None,
    head_sha: str | None,
    summary_file: Path | None,
) -> int:
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    quality_report = artifacts_dir / "quality-scorecard.md"
    autonomy_report = artifacts_dir / "autonomy-kpi-report.md"
    entropy_report = artifacts_dir / "docs-gardening-report.md"
    findings_report = artifacts_dir / "agent-review-findings.md"

    commands: list[tuple[str, Path, list[str]]] = [
        (
            "quality-scorecards",
            quality_report,
            [
                sys.executable,
                "scripts/validate_quality_scorecards.py",
                "--report",
                str(quality_report),
            ],
        ),
        (
            "autonomy-kpi",
            autonomy_report,
            [
                sys.executable,
                "scripts/autonomy_kpi_report.py",
                "--output",
                str(autonomy_report),
            ],
        ),
        (
            "docs-gardening-entropy",
            entropy_report,
            [
                sys.executable,
                "scripts/doc_gardening_report.py",
                "--output",
                str(entropy_report),
            ],
        ),
    ]

    agent_review_cmd = [
        sys.executable,
        "scripts/agent_review.py",
        "--output",
        str(findings_report),
    ]
    if base_sha and head_sha:
        agent_review_cmd.extend(["--base-sha", base_sha, "--head-sha", head_sha])
    commands.append(("agent-review-findings", findings_report, agent_review_cmd))

    results: list[ComponentResult] = []
    for name, artifact, command in commands:
        rc, _, _ = _run_capture(command)
        results.append(ComponentResult(name=name, artifact=artifact, returncode=rc))

    metrics_rc, metrics_stdout, _ = _run_capture(
        [sys.executable, "scripts/harness_baseline_metrics.py"]
    )
    metrics = _parse_metrics(metrics_stdout)

    report = _render_dashboard(components=results, metrics=metrics)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"governance dashboard written: {output.as_posix()}")

    if summary_file is not None:
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        with summary_file.open("a", encoding="utf-8") as handle:
            handle.write(report + "\n")

    failed = [item.name for item in results if item.returncode != 0]
    if metrics_rc != 0:
        failed.append("harness-baseline-metrics")

    if failed:
        print("governance dashboard: FAILED (" + ", ".join(failed) + ")")
        return 1

    print("governance dashboard: OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build one combined governance dashboard artifact (scorecards, KPI, entropy, findings)."
    )
    parser.add_argument("--output", default="governance-dashboard.md")
    parser.add_argument("--artifacts-dir", default=".runlogs/governance-dashboard")
    parser.add_argument("--base-sha", default=None)
    parser.add_argument("--head-sha", default=None)
    parser.add_argument("--summary-file", default=None)
    args = parser.parse_args()

    summary = Path(args.summary_file) if args.summary_file else None
    raise SystemExit(
        run(
            output=Path(args.output),
            artifacts_dir=Path(args.artifacts_dir),
            base_sha=args.base_sha,
            head_sha=args.head_sha,
            summary_file=summary,
        )
    )


if __name__ == "__main__":
    main()
