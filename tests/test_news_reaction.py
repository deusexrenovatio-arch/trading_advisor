from __future__ import annotations

from datetime import datetime, timedelta

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.news.reaction import (
    build_event_study_leakage_audit,
    rebuild_event_market_reactions,
    summarize_event_study,
)
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_event_market_reactions,
    load_news_labels,
    upsert_news_entity_links,
    upsert_news_event_items,
    upsert_news_events,
    upsert_news_items,
    upsert_news_labels,
    upsert_quotes,
)


def _settings(tmp_path):
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-reaction.db"),
    )


def _seed_two_overlapping_events(session):
    base = datetime(2026, 1, 5, 10, 0, 0)
    news_rows = []
    event_rows = []
    event_item_rows = []
    link_rows = []
    label_rows = []
    for idx, ts in enumerate([base, base + timedelta(minutes=20)], start=1):
        news_id = f"news-rx-{idx}"
        event_id = f"evt-rx-{idx}"
        news_rows.append(
            {
                "news_id": news_id,
                "source": "Reuters",
                "url": f"https://example.org/{news_id}",
                "title": f"Event {idx} headline",
                "content": "Commodity supply and demand update.",
                "language": "en",
                "published_at": ts.isoformat() + "Z",
                "ingested_at": ts.isoformat() + "Z",
                "hash": f"hash-{news_id}",
            }
        )
        event_rows.append(
            {
                "event_id": event_id,
                "event_first_published_at_utc": ts.isoformat() + "Z",
                "event_first_ingested_at_utc": ts.isoformat() + "Z",
                "event_last_published_at_utc": ts.isoformat() + "Z",
                "event_status": "active",
                "canonical_summary": f"Event {idx}",
                "canonical_mechanism": "Deterministic fixture for reaction test.",
                "cluster_version": "det-v1",
            }
        )
        event_item_rows.append(
            {
                "event_id": event_id,
                "news_id": news_id,
                "link_role": "primary",
                "similarity_score": 0.99,
                "added_at": ts.isoformat() + "Z",
            }
        )
        link_rows.append(
            {
                "news_id": news_id,
                "entity_type": "instrument",
                "entity_id": "BRN",
                "ticker": "BRN",
                "link_confidence": 0.95,
                "link_stage": "dictionary",
            }
        )
        label_rows.append(
            {
                "target_level": "event",
                "target_id": event_id,
                "commodity_json": ["BRN"],
                "news_type_json": ["SUP_DEC"],
                "direction": "positive" if idx == 1 else "negative",
                "magnitude": 0.8,
                "lag_bucket": "short",
                "relevance": 0.9,
                "confidence": 0.85,
                "label_source": "model",
                "label_version": "v1",
                "model_version": "finbert-v1",
            }
        )

    upsert_news_items(session, news_rows)
    upsert_news_events(session, event_rows)
    upsert_news_event_items(session, event_item_rows)
    upsert_news_entity_links(session, link_rows)
    upsert_news_labels(session, label_rows)

    quote_rows = []
    cursor = base - timedelta(hours=2)
    price = 80.0
    for step in range(80):
        quote_rows.append(
            {
                "secid": "BRN",
                "timestamp": cursor.isoformat() + "Z",
                "last": price,
                "bid": price - 0.02,
                "ask": price + 0.02,
                "volume": 1000 + step,
            }
        )
        cursor += timedelta(minutes=5)
        price += 0.03 if step < 45 else -0.01
    upsert_quotes(session, quote_rows)


def test_rebuild_event_market_reactions_and_overlap_flags(tmp_path):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        _seed_two_overlapping_events(session)
        report = rebuild_event_market_reactions(
            session,
            window_ids=["0_30m"],
            sampling_freqs=["5m"],
            estimation_lookback_days=1,
        )
        reactions = load_event_market_reactions(session, window_id="0_30m", sampling_freq="5m", limit=50)
        labels = load_news_labels(session, target_level="event", limit=20)

    assert report.events_seen >= 2
    assert report.rows_upserted >= 2
    assert len(reactions) >= 2
    assert any(
        isinstance(row.get("quality_flags_json"), dict) and bool(row["quality_flags_json"].get("overlap_event"))
        for row in reactions
    )

    summary = summarize_event_study(reactions=reactions, labels=labels, exclude_overlap=True)
    assert int(summary["sample_count_before_overlap_filter"]) >= int(summary["sample_count"])
    assert int(summary["excluded_overlap_count"]) >= 1
    by_direction = summary["car_summary_by_direction"]
    assert "positive" in by_direction
    assert "negative" in by_direction


def test_event_time_mode_and_leakage_audit(tmp_path):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    base_published = datetime(2026, 1, 5, 10, 0, 0)
    base_ingested = base_published + timedelta(minutes=20)
    with session_factory() as session:
        upsert_news_items(
            session,
            [
                {
                    "news_id": "news-rx-leak-1",
                    "source": "Reuters",
                    "url": "https://example.org/news-rx-leak-1",
                    "title": "Leakage fixture headline",
                    "content": "Fixture content for leakage audit.",
                    "language": "en",
                    "published_at": base_published.isoformat() + "Z",
                    "ingested_at": base_ingested.isoformat() + "Z",
                    "hash": "hash-news-rx-leak-1",
                }
            ],
        )
        upsert_news_events(
            session,
            [
                {
                    "event_id": "evt-rx-leak-1",
                    "event_first_published_at_utc": base_published.isoformat() + "Z",
                    "event_first_ingested_at_utc": base_ingested.isoformat() + "Z",
                    "event_last_published_at_utc": base_published.isoformat() + "Z",
                    "event_status": "active",
                    "canonical_summary": "Leakage fixture event",
                    "canonical_mechanism": "Fixture",
                    "cluster_version": "det-v1",
                }
            ],
        )
        upsert_news_event_items(
            session,
            [
                {
                    "event_id": "evt-rx-leak-1",
                    "news_id": "news-rx-leak-1",
                    "link_role": "primary",
                    "similarity_score": 0.99,
                    "added_at": base_ingested.isoformat() + "Z",
                }
            ],
        )
        upsert_news_entity_links(
            session,
            [
                {
                    "news_id": "news-rx-leak-1",
                    "entity_type": "instrument",
                    "entity_id": "BRN",
                    "ticker": "BRN",
                    "link_confidence": 0.95,
                    "link_stage": "dictionary",
                }
            ],
        )

        quote_rows = []
        cursor = base_published - timedelta(hours=2)
        price = 79.5
        for step in range(80):
            quote_rows.append(
                {
                    "secid": "BRN",
                    "timestamp": cursor.isoformat() + "Z",
                    "last": price,
                    "bid": price - 0.02,
                    "ask": price + 0.02,
                    "volume": 1200 + step,
                }
            )
            cursor += timedelta(minutes=5)
            price += 0.02
        upsert_quotes(session, quote_rows)

        _ = rebuild_event_market_reactions(
            session,
            event_ids=["evt-rx-leak-1"],
            window_ids=["0_30m"],
            sampling_freqs=["5m"],
            estimation_lookback_days=1,
            event_time_mode="published",
        )
        reactions = load_event_market_reactions(session, event_ids=["evt-rx-leak-1"], limit=50)
        events = [
            {
                "event_id": "evt-rx-leak-1",
                "event_first_published_at_utc": base_published.isoformat() + "Z",
                "event_first_ingested_at_utc": base_ingested.isoformat() + "Z",
            }
        ]

    assert reactions
    assert any(
        isinstance(row.get("quality_flags_json"), dict)
        and str(row["quality_flags_json"].get("event_time_mode")) == "published"
        for row in reactions
    )

    published_audit = build_event_study_leakage_audit(
        reactions=reactions,
        events=events,
        event_time_mode="published",
    )
    ingested_audit = build_event_study_leakage_audit(
        reactions=reactions,
        events=events,
        event_time_mode="ingested",
    )
    assert int(published_audit["checked_rows"]) >= 1
    assert int(published_audit["violation_count"]) >= 1
    assert float(ingested_audit["violation_rate"]) == 0.0
