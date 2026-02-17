from __future__ import annotations

from datetime import datetime, timedelta

from moex_carry.news.events import cluster_news_events, compute_event_fragmentation_report
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.storage.repositories import (
    load_news_event_items,
    load_news_events,
    load_news_items,
    upsert_news_entity_links,
    upsert_news_items,
)


def _setup_session(tmp_path):
    settings = AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-events.db"),
    )
    engine = create_engine_from_settings(settings)
    init_db(engine)
    return create_session_factory(engine)


def test_deterministic_event_clustering_update_and_refute(tmp_path):
    session_factory = _setup_session(tmp_path)
    base_ts = datetime.utcnow().replace(microsecond=0)
    rows = [
        {
            "news_id": "news-oil-1",
            "source": "Reuters",
            "url": "https://example.org/news-oil-1",
            "title": "OPEC cuts oil output by 1 million barrels per day",
            "content": "The cartel agreed supply reductions.",
            "language": "en",
            "published_at": base_ts.isoformat() + "Z",
            "ingested_at": base_ts.isoformat() + "Z",
            "hash": "hash-news-oil-1",
        },
        {
            "news_id": "news-oil-2",
            "source": "Reuters",
            "url": "https://example.org/news-oil-2",
            "title": "Update: OPEC cuts oil output by 1 million barrels per day",
            "content": "Updated details from ministerial meeting.",
            "language": "en",
            "published_at": (base_ts + timedelta(minutes=20)).isoformat() + "Z",
            "ingested_at": (base_ts + timedelta(minutes=20)).isoformat() + "Z",
            "hash": "hash-news-oil-2",
        },
        {
            "news_id": "news-oil-3",
            "source": "Bloomberg",
            "url": "https://example.org/news-oil-3",
            "title": "Officials deny OPEC cut rumor",
            "content": "The ministry refuted reports about immediate cuts.",
            "language": "en",
            "published_at": (base_ts + timedelta(minutes=40)).isoformat() + "Z",
            "ingested_at": (base_ts + timedelta(minutes=40)).isoformat() + "Z",
            "hash": "hash-news-oil-3",
        },
    ]
    with session_factory() as session:
        upsert_news_items(session, rows)
        upsert_news_entity_links(
            session,
            [
                {
                    "news_id": "news-oil-1",
                    "entity_type": "commodity",
                    "entity_id": "BRN",
                    "ticker": "BRN",
                    "link_confidence": 0.95,
                    "link_stage": "dictionary",
                },
                {
                    "news_id": "news-oil-2",
                    "entity_type": "commodity",
                    "entity_id": "BRN",
                    "ticker": "BRN",
                    "link_confidence": 0.95,
                    "link_stage": "dictionary",
                },
                {
                    "news_id": "news-oil-3",
                    "entity_type": "commodity",
                    "entity_id": "BRN",
                    "ticker": "BRN",
                    "link_confidence": 0.95,
                    "link_stage": "dictionary",
                },
            ],
        )
        news_rows = load_news_items(session, limit=20)
        report = cluster_news_events(
            session,
            news_rows=news_rows,
            cluster_window_hours=48,
            similarity_threshold=0.2,
            resolve_after_hours=100_000,
            cluster_version="det-v1",
        )
        assert report.created_events == 1
        assert report.updated_events >= 1
        assert report.refuted_events >= 1
        assert report.linked_news >= 3

        events = load_news_events(session, limit=10)
        assert len(events) == 1
        assert events[0]["event_status"] == "refuted"

        event_items = load_news_event_items(session, event_ids=[events[0]["event_id"]], limit=10)
        assert len(event_items) == 3
        roles = {str(row.get("link_role") or "") for row in event_items}
        assert "primary" in roles
        assert "update" in roles or "duplicate" in roles
        assert "refute" in roles

        fragmentation = compute_event_fragmentation_report(session)
        assert fragmentation["events_total"] == 1
        assert fragmentation["event_links_total"] == 3
        assert fragmentation["multi_news_events"] == 1


def test_resolve_old_events(tmp_path):
    session_factory = _setup_session(tmp_path)
    old_ts = datetime(2024, 1, 10, 10, 0, 0)
    with session_factory() as session:
        upsert_news_items(
            session,
            [
                {
                    "news_id": "news-gas-old",
                    "source": "Reuters",
                    "url": "https://example.org/news-gas-old",
                    "title": "Gas disruption in pipeline",
                    "content": "Unexpected outage hits supply.",
                    "language": "en",
                    "published_at": old_ts.isoformat() + "Z",
                    "ingested_at": old_ts.isoformat() + "Z",
                    "hash": "hash-news-gas-old",
                }
            ],
        )
        upsert_news_entity_links(
            session,
            [
                {
                    "news_id": "news-gas-old",
                    "entity_type": "commodity",
                    "entity_id": "NG_US",
                    "ticker": "NG_US",
                    "link_confidence": 0.9,
                    "link_stage": "dictionary",
                }
            ],
        )
        report = cluster_news_events(
            session,
            news_rows=load_news_items(session, limit=10),
            cluster_window_hours=48,
            similarity_threshold=0.2,
            resolve_after_hours=1,
            cluster_version="det-v1",
        )
        assert report.created_events >= 1
        assert report.resolved_events >= 1
        events = load_news_events(session, limit=10)
        assert events[0]["event_status"] == "resolved"
