from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import measure_dev_loop  # noqa: E402


def test_measure_dev_loop_reports_p95_and_cold_warm_breakdown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "timing.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "profiles": {
                    "surface_docs": {
                        "description": "docs profile",
                        "commands": [{"name": "docs_gate", "cmd": ["echo", "ok"]}],
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    json_out = tmp_path / "report.json"
    md_out = tmp_path / "report.md"

    durations = iter([0.9, 0.6, 0.5])

    def _fake_run_command(_command, _iteration: int, _total_iterations: int) -> tuple[int, float]:
        return 0, next(durations)

    monkeypatch.setattr(measure_dev_loop, "_run_command", _fake_run_command)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "measure_dev_loop.py",
            "--config",
            str(config_path),
            "--profiles",
            "surface_docs",
            "--iterations",
            "3",
            "--json-out",
            str(json_out),
            "--report-out",
            str(md_out),
        ],
    )

    assert measure_dev_loop.main() == 0

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    profile = payload["profiles"][0]
    command_stats = profile["command_stats"][0]

    assert command_stats["p95_sec"] >= command_stats["median_sec"]
    assert command_stats["cold_sec"] == 0.9
    assert command_stats["warm_summary"]["median_sec"] == 0.55
    rendered = md_out.read_text(encoding="utf-8")
    assert "cold/warm" in rendered
    assert "P95" in rendered
