from __future__ import annotations

from datetime import datetime, timedelta

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    upsert_news_entity_links,
    upsert_news_event_items,
    upsert_news_events,
    upsert_news_items,
    upsert_news_labels,
    upsert_quotes,
)
from moex_carry.server import create_server_app as create_app


def _settings(tmp_path):
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-stage-d-api.db"),
    )


def _seed_runtime_without_reactions(session):
    ts = datetime(2026, 1, 12, 9, 0, 0)
    upsert_news_items(
        session,
        [
            {
                "news_id": "news-d-api-1",
                "source": "Reuters",
                "url": "https://example.org/news-d-api-1",
                "title": "Supply outage lifts brent futures",
                "content": "Short-term shortage in export infrastructure.",
                "language": "en",
                "published_at": ts.isoformat() + "Z",
                "ingested_at": ts.isoformat() + "Z",
                "hash": "hash-news-d-api-1",
            }
        ],
    )
    upsert_news_events(
        session,
        [
            {
                "event_id": "evt-d-api-1",
                "event_first_published_at_utc": ts.isoformat() + "Z",
                "event_first_ingested_at_utc": ts.isoformat() + "Z",
                "event_last_published_at_utc": ts.isoformat() + "Z",
                "event_status": "active",
                "canonical_summary": "Brent outage",
                "canonical_mechanism": "Supply disruption supports nearby futures.",
                "cluster_version": "det-v1",
            }
        ],
    )
    upsert_news_event_items(
        session,
        [
            {
                "event_id": "evt-d-api-1",
                "news_id": "news-d-api-1",
                "link_role": "primary",
                "similarity_score": 0.99,
                "added_at": ts.isoformat() + "Z",
            }
        ],
    )
    upsert_news_entity_links(
        session,
        [
            {
                "news_id": "news-d-api-1",
                "entity_type": "instrument",
                "entity_id": "BRN",
                "ticker": "BRN",
                "link_confidence": 0.96,
                "link_stage": "dictionary",
            }
        ],
    )
    upsert_news_labels(
        session,
        [
            {
                "target_level": "event",
                "target_id": "evt-d-api-1",
                "commodity_json": ["BRN"],
                "news_type_json": ["SUP_DEC"],
                "direction": "positive",
                "magnitude": 0.9,
                "lag_bucket": "short",
                "relevance": 0.95,
                "confidence": 0.9,
                "label_source": "model",
                "label_version": "v1",
                "model_version": "finbert-v1",
            }
        ],
    )

    quote_rows = []
    cursor = ts - timedelta(hours=2)
    price = 75.0
    for idx in range(60):
        quote_rows.append(
            {
                "secid": "BRN",
                "timestamp": cursor.isoformat() + "Z",
                "last": price,
                "bid": price - 0.01,
                "ask": price + 0.01,
                "volume": 800 + idx,
            }
        )
        cursor += timedelta(minutes=5)
        price += 0.02
    upsert_quotes(session, quote_rows)


def test_validation_event_study_rebuilds_reactions_if_missing(tmp_path):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_runtime_without_reactions(session)

    app = create_app(settings)
    client = app.server.test_client()

    response = client.get(
        "/api/v2/validation/event-study"
        "?commodity=BRN&window_id=0_30m&sampling_freq=5m&rebuild_if_missing=true"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["sample_count"] >= 1
    assert isinstance(payload.get("rebuild_report"), dict)
    assert int(payload["rebuild_report"]["rows_upserted"]) >= 1
    assert "car_summary_by_direction" in payload

