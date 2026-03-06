from __future__ import annotations

from pathlib import Path

import pandas as pd

from moex_carry.news_root_maintenance import RootMaintenanceConfig, refresh_root_maintenance
from moex_carry.news_shock_store import upsert_live_shock_rows
from moex_carry.news_storage import open_sqlite_connection, sqlite_path_from_url


def _db_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_refresh_root_maintenance_builds_links_registry_and_edges(tmp_path: Path) -> None:
    db_path = tmp_path / "news_root.db"
    frame = pd.DataFrame(
        [
            {
                "symbol": "BRN",
                "shock_ts": "2026-02-01T10:00:00Z",
                "bar_minutes": 5,
                "prev_price": 80.0,
                "price": 81.2,
                "logret": 0.0148,
                "abs_move_pct": 1.5,
                "shock_direction": "up",
                "rolling_sigma": 0.003,
                "z_score": 3.8,
                "selected_event_source": "root",
                "selected_event_id": "evt-1",
                "selected_event_ts": "2026-02-01T09:55:00Z",
                "selected_delay_min": 5.0,
                "selected_match_mode": "root_strict",
                "selected_title": "Shipping halted near Hormuz",
                "selected_url": "https://example.com/root-1",
                "selected_cause_event": "chokepoint_closure",
                "selected_cause_route_key": "chokepoint:hormuz->seaborne_crude->BRN",
                "selected_cause_claim_status": "confirmed",
                "selected_cause_classification": "cause",
                "selected_cause_confidence": 0.88,
                "selected_fundamental_score": 0.91,
                "selected_direction_alignment": 1.0,
                "selected_is_primary_cause": 1,
                "root_link_type": "primary",
                "root_primary_shock_ts": "2026-02-01T10:00:00Z",
                "root_episode_event_index": 1,
                "root_topic_id": "root:BRN:mideast_geopolitics",
            },
            {
                "symbol": "BRN",
                "shock_ts": "2026-02-01T11:00:00Z",
                "bar_minutes": 5,
                "prev_price": 81.2,
                "price": 81.8,
                "logret": 0.0073,
                "abs_move_pct": 0.74,
                "shock_direction": "up",
                "rolling_sigma": 0.0029,
                "z_score": 2.5,
                "selected_event_source": "root",
                "selected_event_id": "evt-1",
                "selected_event_ts": "2026-02-01T10:50:00Z",
                "selected_delay_min": 10.0,
                "selected_match_mode": "root_context",
                "selected_title": "Insurers raise war-risk premiums",
                "selected_url": "https://example.com/root-2",
                "selected_cause_event": "chokepoint_closure",
                "selected_cause_route_key": "chokepoint:hormuz->seaborne_crude->BRN",
                "selected_cause_claim_status": "confirmed",
                "selected_cause_classification": "mixed",
                "selected_cause_confidence": 0.73,
                "selected_fundamental_score": 0.77,
                "selected_direction_alignment": 1.0,
                "selected_is_primary_cause": 0,
                "root_link_type": "aftershock",
                "root_primary_shock_ts": "2026-02-01T10:00:00Z",
                "root_episode_event_index": 2,
                "root_topic_id": "root:BRN:mideast_geopolitics",
            },
        ]
    )
    upsert_live_shock_rows(frame=frame, database_url=_db_url(db_path), data_dir=tmp_path)

    report = refresh_root_maintenance(
        database_url=_db_url(db_path),
        data_dir=tmp_path,
        cfg=RootMaintenanceConfig(bar_minutes=5),
    )
    assert report["links_upserted"] == 2
    assert report["registry_upserted"] == 1
    assert report["edges_upserted"] >= 2

    conn = open_sqlite_connection(sqlite_path_from_url(_db_url(db_path), data_dir=tmp_path), timeout_sec=10.0, write=False)
    try:
        link_count = conn.execute("SELECT COUNT(*) FROM news_root_links").fetchone()[0]
        registry = conn.execute(
            "SELECT shock_count, primary_count, aftershock_count FROM news_root_registry"
        ).fetchone()
        edge_count = conn.execute("SELECT COUNT(*) FROM news_root_route_edges").fetchone()[0]
    finally:
        conn.close()

    assert int(link_count) == 2
    assert tuple(registry) == (2, 1, 1)
    assert int(edge_count) >= 2
