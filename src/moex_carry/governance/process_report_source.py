from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from moex_carry.governance.process_reports import build_process_report, load_task_outcomes


@dataclass(frozen=True)
class ProcessReportSourceConfig:
    snapshot_path: Path
    task_outcomes_path: Path


class ProcessReportSourceError(RuntimeError):
    def __init__(self, message: str, *, source_path: Path):
        super().__init__(message)
        self.source_path = source_path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_process_report_snapshot_path() -> Path:
    configured = os.getenv("MOEX_CARRY_PROCESS_REPORT_PATH", "").strip()
    if configured:
        return Path(configured)
    return _repo_root() / ".runlogs" / "governance-dashboard" / "process-improvement-report.json"


def default_task_outcomes_path() -> Path:
    configured = os.getenv("MOEX_CARRY_TASK_OUTCOMES_PATH", "").strip()
    if configured:
        return Path(configured)
    return _repo_root() / "memory" / "task_outcomes.yaml"


def resolve_process_report_source_config() -> ProcessReportSourceConfig:
    return ProcessReportSourceConfig(
        snapshot_path=default_process_report_snapshot_path(),
        task_outcomes_path=default_task_outcomes_path(),
    )


def _load_snapshot_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive guard
        raise ProcessReportSourceError("invalid process report snapshot", source_path=path) from exc
    if not isinstance(payload, dict):
        raise ProcessReportSourceError("process report snapshot must be a JSON object", source_path=path)
    return payload


def _with_query(report: dict[str, Any], *, weeks: int, window_size: int) -> dict[str, Any]:
    normalized = dict(report)
    normalized["query"] = {
        "weeks": weeks,
        "window_size": window_size,
    }
    return normalized


def build_process_report_payload(
    *,
    weeks: int,
    window_size: int,
    source: ProcessReportSourceConfig | None = None,
) -> tuple[dict[str, Any], Path]:
    config = source or resolve_process_report_source_config()
    if config.snapshot_path.exists():
        snapshot_report = _load_snapshot_report(config.snapshot_path)
        return _with_query(snapshot_report, weeks=weeks, window_size=window_size), config.snapshot_path

    try:
        outcomes_payload = load_task_outcomes(config.task_outcomes_path)
        report = build_process_report(outcomes_payload, window_size=window_size, max_weeks=weeks)
    except Exception as exc:
        raise ProcessReportSourceError(
            "unable to build process report from task outcomes",
            source_path=config.task_outcomes_path,
        ) from exc
    return _with_query(report, weeks=weeks, window_size=window_size), config.task_outcomes_path
