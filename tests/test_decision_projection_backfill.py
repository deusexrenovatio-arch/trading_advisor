from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.decision_projection import compute_projection_parity
from moex_carry.storage.repositories import load_decision_view_projection


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _run_script(*args: str, repo_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    return subprocess.run(
        [sys.executable, "scripts/backfill_decision_projection.py", *args],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_compute_projection_parity_reports_field_mismatches():
    source = [
        {
            "decision_id": "dec-1",
            "created_at": "2025-01-01T10:00:00Z",
            "strategy_type": "arbitrage",
            "primary_instrument": "SBER",
            "action": "hold",
            "risk_state": "green",
            "news_severity": "low",
        },
        {
            "decision_id": "dec-2",
            "created_at": "2025-01-01T11:00:00Z",
            "strategy_type": "arbitrage",
            "primary_instrument": "GAZP",
            "action": "hold",
            "risk_state": "yellow",
            "news_severity": "medium",
        },
    ]
    db = [
        {
            "decision_id": "dec-1",
            "created_at": "2025-01-01T10:00:00+00:00",
            "strategy_type": "arbitrage",
            "primary_instrument": "SBER",
            "action": "hold",
            "risk_state": "green",
            "news_severity": "low",
        },
        {
            "decision_id": "dec-2",
            "created_at": "2025-01-01T11:00:00Z",
            "strategy_type": "arbitrage",
            "primary_instrument": "GAZP",
            "action": "hold",
            "risk_state": "red",
            "news_severity": "medium",
        },
    ]

    report = compute_projection_parity(source, db, sample_mismatches=10)
    assert report["total_source_rows"] == 2
    assert report["matched_rows"] == 1
    assert report["field_mismatches"] == 1
    assert report["parity_ratio"] == 0.5


def test_backfill_script_all_mode_and_parity_threshold(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "data"
    db_path = tmp_path / "decision-projection.db"
    source_path = data_dir / "decisions" / "decision_view.jsonl"
    _write_jsonl(
        source_path,
        [
            {
                "decision_id": "dec-a",
                "created_at": "2025-01-01T10:00:00Z",
                "strategy_type": "arbitrage",
                "primary_instrument": "SBER",
                "action": "hold",
                "risk_state": "green",
                "news_severity": "low",
            },
            {
                "decision_id": "dec-b",
                "created_at": "2025-01-01T11:00:00Z",
                "strategy_type": "arbitrage",
                "primary_instrument": "GAZP",
                "action": "hold",
                "risk_state": "yellow",
                "news_severity": "medium",
            },
        ],
    )

    result = _run_script(
        "--mode",
        "all",
        "--data-dir",
        str(data_dir),
        "--db-url",
        f"sqlite:///{db_path}",
        "--parity-threshold",
        "1.0",
        repo_root=repo_root,
    )
    assert result.returncode == 0, result.stderr
    assert "parity check passed" in result.stdout

    settings = AppSettings(
        data=DataConfig(data_dir=str(data_dir)),
        database=DatabaseConfig(url=f"sqlite:///{db_path}"),
    )
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        rows = load_decision_view_projection(session, limit=0)
    assert len(rows) == 2

    _write_jsonl(
        source_path,
        [
            {
                "decision_id": "dec-a",
                "created_at": "2025-01-01T10:00:00Z",
                "strategy_type": "arbitrage",
                "primary_instrument": "SBER",
                "action": "hold",
                "risk_state": "red",
                "news_severity": "low",
            }
        ],
    )
    parity_only = _run_script(
        "--mode",
        "parity",
        "--data-dir",
        str(data_dir),
        "--db-url",
        f"sqlite:///{db_path}",
        "--parity-threshold",
        "1.0",
        repo_root=repo_root,
    )
    assert parity_only.returncode == 2
    assert "parity check failed" in parity_only.stdout
