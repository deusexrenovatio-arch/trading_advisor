from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class CheckResult:
    dimension: str
    check_id: str
    command: list[str]
    returncode: int


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("scorecards config must be YAML object")
    return payload


def _normalize_command(raw: list[Any]) -> list[str]:
    out: list[str] = []
    for token in raw:
        value = str(token)
        out.append(sys.executable if value == "{python}" else value)
    return out


def _render_report(
    *,
    per_dimension: dict[str, tuple[float, float, int, int]],
    results: list[CheckResult],
    failed_dimensions: list[str],
) -> str:
    lines = [
        "# Quality Scorecards",
        "",
        "| Dimension | Score | Threshold | Passed/Total |",
        "| --- | --- | --- | --- |",
    ]
    for dimension, (score, threshold, passed, total) in sorted(per_dimension.items()):
        lines.append(f"| `{dimension}` | {score:.2f} | {threshold:.2f} | {passed}/{total} |")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    lines.append("| Dimension | Check | Status | Command |")
    lines.append("| --- | --- | --- | --- |")
    for item in results:
        status = "pass" if item.returncode == 0 else "fail"
        cmd = " ".join(item.command)
        lines.append(f"| `{item.dimension}` | `{item.check_id}` | {status} | `{cmd}` |")
    lines.append("")
    if failed_dimensions:
        lines.append("## Blocking Dimensions")
        for dim in failed_dimensions:
            lines.append(f"- {dim}")
    else:
        lines.append("Status: OK")
    lines.append("")
    return "\n".join(lines)


def run(config_path: Path, report_path: Path | None, summary_file: Path | None) -> int:
    if not config_path.exists():
        print(f"quality scorecards config missing: {config_path.as_posix()}")
        return 1

    config = _load_yaml(config_path)
    if config.get("version") != 1:
        print(f"quality scorecards config has unsupported version: {config.get('version')!r}")
        return 1

    dims_raw = config.get("dimensions")
    if not isinstance(dims_raw, list) or not dims_raw:
        print("quality scorecards config must define non-empty list 'dimensions'")
        return 1

    results: list[CheckResult] = []
    per_dimension: dict[str, tuple[float, float, int, int]] = {}
    failed_dimensions: list[str] = []

    for dim_raw in dims_raw:
        if not isinstance(dim_raw, dict):
            print("quality scorecards config invalid: each dimension must be object")
            return 1
        dim_id = str(dim_raw.get("id", "")).strip()
        if not dim_id:
            print("quality scorecards config invalid: dimension id is required")
            return 1
        threshold = float(dim_raw.get("threshold", 1.0))
        checks = dim_raw.get("checks")
        if not isinstance(checks, list) or not checks:
            print(f"quality scorecards config invalid: dimension '{dim_id}' has no checks")
            return 1

        passed = 0
        total = 0
        for check_raw in checks:
            if not isinstance(check_raw, dict):
                print(f"quality scorecards config invalid: check in '{dim_id}' must be object")
                return 1
            check_id = str(check_raw.get("id", "")).strip() or f"{dim_id}-check-{total + 1}"
            command_raw = check_raw.get("command")
            if not isinstance(command_raw, list) or not command_raw:
                print(f"quality scorecards config invalid: '{dim_id}/{check_id}' has empty command")
                return 1
            command = _normalize_command(command_raw)
            print(f">>> scorecard[{dim_id}/{check_id}] {' '.join(command)}")
            completed = subprocess.run(command, check=False)
            rc = int(completed.returncode)
            results.append(CheckResult(dim_id, check_id, command, rc))
            total += 1
            if rc == 0:
                passed += 1

        score = (passed / total) if total else 0.0
        per_dimension[dim_id] = (score, threshold, passed, total)
        if score < threshold:
            failed_dimensions.append(dim_id)

    report = _render_report(
        per_dimension=per_dimension,
        results=results,
        failed_dimensions=sorted(failed_dimensions),
    )

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        print(f"quality scorecards report written: {report_path.as_posix()}")
    if summary_file is not None:
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        with summary_file.open("a", encoding="utf-8") as handle:
            handle.write(report + "\n")

    if failed_dimensions:
        print("quality scorecards: FAILED")
        return 1
    print("quality scorecards: OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate quality scorecards with blocking thresholds.")
    parser.add_argument("--config", default="configs/quality_scorecards.yaml")
    parser.add_argument("--report", default=None)
    parser.add_argument("--summary-file", default=None)
    args = parser.parse_args()
    report_path = Path(args.report) if args.report else None
    summary_path = Path(args.summary_file) if args.summary_file else None
    sys.exit(run(Path(args.config), report_path, summary_path))


if __name__ == "__main__":
    main()
