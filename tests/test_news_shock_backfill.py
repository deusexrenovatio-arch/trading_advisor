from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from moex_carry.config import AppSettings, DataConfig
from moex_carry.news_live_runtime import CommodityProfile, NewsIngestConfig
from moex_carry.news_shock_backfill import ShockRowsBackfillConfig, run_shock_rows_backfill


def _db_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(data=DataConfig(data_dir=str(tmp_path)))


def _news_cfg(tmp_path: Path) -> NewsIngestConfig:
    return NewsIngestConfig(
        database_url=_db_url(tmp_path / "news_live.db"),
        commodity_profiles=(
            CommodityProfile(
                ticker="NG_US",
                name="US Natural Gas",
                gdelt_query="natural gas",
                newsapi_query="natural gas",
            ),
        ),
        data_dir=str(tmp_path),
        gdelt_enabled=False,
        newsapi_enabled=False,
    )


def test_shock_backfill_writes_rows_and_moves_cursor(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    news_cfg = _news_cfg(tmp_path)
    end_utc = datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)
    start_utc = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)

    def _fake_build_live_shock_input(*, end_utc, **_kwargs):  # type: ignore[no-redef]
        ts = end_utc - timedelta(hours=1)
        return pd.DataFrame(
            [
                {
                    "symbol": "NG_US",
                    "shock_ts": ts.isoformat().replace("+00:00", "Z"),
                    "bar_minutes": 5,
                    "shock_direction": "up",
                    "z_score": 3.1,
                }
            ]
        )

    monkeypatch.setattr(
        "moex_carry.news_shock_backfill.build_live_shock_input",
        _fake_build_live_shock_input,
    )

    result = run_shock_rows_backfill(
        settings=settings,
        news_config=news_cfg,
        cfg=ShockRowsBackfillConfig(
            cursor_key="test_backfill_cursor",
            start_utc=start_utc,
            end_utc=end_utc,
            window_hours=24,
            windows_per_run=2,
            bar_minutes=5,
            min_abs_z=2.0,
        ),
    )
    assert int(result["windows_processed"]) == 2
    assert int(result["rows_upserted_total"]) == 2
    assert bool(result["done"]) is False

    db_path = tmp_path / "news_live.db"
    conn = sqlite3.connect(str(db_path))
    try:
        shock_count = conn.execute("SELECT COUNT(*) FROM news_shock_rows").fetchone()[0]
        cursor = conn.execute(
            "SELECT state_value FROM news_state WHERE state_key = 'test_backfill_cursor'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert int(shock_count) == 2
    assert str(cursor).startswith("2026-03-02T12:00:00")


def test_shock_backfill_stops_when_cursor_reaches_start(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    news_cfg = _news_cfg(tmp_path)
    start_utc = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    end_utc = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(
        "moex_carry.news_shock_backfill.build_live_shock_input",
        lambda **_kwargs: pd.DataFrame(),
    )

    result = run_shock_rows_backfill(
        settings=settings,
        news_config=news_cfg,
        cfg=ShockRowsBackfillConfig(
            cursor_key="test_backfill_cursor_done",
            start_utc=start_utc,
            end_utc=end_utc,
            windows_per_run=1,
        ),
    )
    assert bool(result["done"]) is True
    assert int(result["windows_processed"]) == 0
