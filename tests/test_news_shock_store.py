from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from moex_carry.news_shock_store import read_live_shock_rows, upsert_live_shock_rows


def _db_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_upsert_live_shock_rows_writes_sqlite_table(tmp_path: Path) -> None:
    db_path = tmp_path / "live_shocks.db"
    frame = pd.DataFrame(
        [
            {
                "symbol": "NG_US",
                "shock_ts": "2026-03-04T09:00:00Z",
                "bar_minutes": 5,
                "prev_ts": "2026-03-04T08:55:00Z",
                "prev_price": 2.45,
                "price": 2.51,
                "logret": 0.0242,
                "abs_move_pct": 2.46,
                "shock_direction": "up",
                "rolling_sigma": 0.0052,
                "z_score": 4.65,
                "selected_event_id": "newsapi-ng-weather-1",
                "selected_title": "Cold snap boosts U.S. gas demand outlook",
                "selected_match_mode": "v2_strict",
                "label_has_any": 1,
                "label_has_silver": 1,
                "label_silver_direction": "up",
                "silver_direction_match": 1,
            }
        ]
    )
    upserted = upsert_live_shock_rows(
        frame=frame,
        database_url=_db_url(db_path),
        data_dir=tmp_path,
    )
    assert int(upserted) == 1

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            """
            SELECT symbol, shock_ts, bar_minutes, selected_event_id, label_has_silver, label_silver_direction
            FROM news_shock_rows
            """
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "NG_US"
    assert row[1] == "2026-03-04T09:00:00Z"
    assert int(row[2]) == 5
    assert row[3] == "newsapi-ng-weather-1"
    assert int(row[4]) == 1
    assert row[5] == "up"


def test_read_live_shock_rows_filters_by_time_and_bar_minutes(tmp_path: Path) -> None:
    db_path = tmp_path / "live_shocks.db"
    frame = pd.DataFrame(
        [
            {
                "symbol": "BRN",
                "shock_ts": "2026-03-04T08:00:00Z",
                "bar_minutes": 5,
                "z_score": 3.0,
            },
            {
                "symbol": "BRN",
                "shock_ts": "2026-03-04T09:00:00Z",
                "bar_minutes": 60,
                "z_score": 2.8,
            },
        ]
    )
    upsert_live_shock_rows(
        frame=frame,
        database_url=_db_url(db_path),
        data_dir=tmp_path,
    )
    out = read_live_shock_rows(
        database_url=_db_url(db_path),
        data_dir=tmp_path,
        start_ts="2026-03-04T08:30:00Z",
        end_ts="2026-03-04T10:00:00Z",
        bar_minutes=60,
    )
    assert int(len(out)) == 1
    assert str(out.iloc[0]["shock_ts"]) == "2026-03-04T09:00:00Z"
    assert int(pd.to_numeric(out.iloc[0]["bar_minutes"], errors="coerce") or 0) == 60
