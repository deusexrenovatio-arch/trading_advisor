from __future__ import annotations

from datetime import datetime

from sqlalchemy import inspect

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_event_market_reactions,
    load_news_annotations,
    load_news_event_items,
    load_news_events,
    load_news_impact_scores,
    load_news_labels,
    load_news_llm_runs,
    load_news_signal_links,
    upsert_event_market_reactions,
    upsert_news_annotations,
    upsert_news_event_items,
    upsert_news_events,
    upsert_news_impact_scores,
    upsert_news_items,
    upsert_news_labels,
    upsert_news_llm_runs,
    upsert_news_signal_links,
)


def test_stage_a_storage_models_and_columns(tmp_path):
    settings = AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/stage-a-news.db"),
    )
    engine = create_engine_from_settings(settings)
    init_db(engine)
    inspector = inspect(engine)

    table_names = set(inspector.get_table_names())
    assert "news_events" in table_names
    assert "news_event_items" in table_names
    assert "news_labels" in table_names
    assert "news_llm_runs" in table_names
    assert "event_market_reactions" in table_names
    assert "news_annotations" in table_names

    impact_columns = {column["name"] for column in inspector.get_columns("news_impact_scores")}
    assert "target_level" in impact_columns
    assert "target_id" in impact_columns

    link_columns = {column["name"] for column in inspector.get_columns("news_signal_links")}
    assert "event_id" in link_columns

    session_factory = create_session_factory(engine)
    now = datetime(2026, 1, 10, 11, 0, 0)
    with session_factory() as session:
        upsert_news_items(
            session,
            [
                {
                    "news_id": "news-gold-1",
                    "source": "Reuters",
                    "url": "https://example.org/news-gold-1",
                    "title": "Gold supply risk event",
                    "content": "Unexpected outage tightens supply.",
                    "language": "en",
                    "published_at": now.isoformat() + "Z",
                    "ingested_at": now.isoformat() + "Z",
                    "hash": "hash-gold-1",
                }
            ],
        )
        upsert_news_events(
            session,
            [
                {
                    "event_id": "evt-gold-1",
                    "event_first_published_at_utc": now.isoformat() + "Z",
                    "event_first_ingested_at_utc": now.isoformat() + "Z",
                    "event_last_published_at_utc": now.isoformat() + "Z",
                    "event_status": "active",
                    "canonical_summary": "Gold outage risk",
                    "canonical_mechanism": "Supply drops, futures react up.",
                    "cluster_version": "v1",
                }
            ],
        )
        upsert_news_event_items(
            session,
            [
                {
                    "event_id": "evt-gold-1",
                    "news_id": "news-gold-1",
                    "link_role": "primary",
                    "similarity_score": 0.97,
                    "added_at": now.isoformat() + "Z",
                }
            ],
        )
        upsert_news_labels(
            session,
            [
                {
                    "target_level": "event",
                    "target_id": "evt-gold-1",
                    "commodity_json": ["GOLD"],
                    "news_type_json": ["SUP_DEC"],
                    "direction": "positive",
                    "magnitude": 0.8,
                    "lag_bucket": "short",
                    "relevance": 0.9,
                    "confidence": 0.86,
                    "label_source": "model",
                    "label_version": "v1",
                    "model_version": "finbert-v1",
                }
            ],
        )
        upsert_news_llm_runs(
            session,
            [
                {
                    "target_level": "event",
                    "target_id": "evt-gold-1",
                    "provider": "openai",
                    "model_id": "gpt-5",
                    "prompt_version": "news-v1",
                    "status": "done",
                    "token_in": 320,
                    "token_out": 74,
                    "latency_ms": 1400,
                }
            ],
        )
        upsert_news_impact_scores(
            session,
            [
                {
                    "news_id": "news-gold-1",
                    "target_level": "event",
                    "target_id": "evt-gold-1",
                    "model_id": "finbert",
                    "model_version": "v1",
                    "direction": "up",
                    "prob_up": 0.84,
                    "prob_down": 0.08,
                    "prob_neutral": 0.08,
                    "impact_score": 0.79,
                    "inference_ts": now.isoformat() + "Z",
                }
            ],
        )
        upsert_news_signal_links(
            session,
            [
                {
                    "link_id": "lnk-stage-a-1",
                    "event_id": "evt-gold-1",
                    "news_id": "news-gold-1",
                    "signal_id": "sig-1",
                    "link_type": "used_in_decision",
                    "gate_action": "allow",
                    "window_start": now.isoformat() + "Z",
                    "window_end": now.isoformat() + "Z",
                }
            ],
        )
        upsert_event_market_reactions(
            session,
            [
                {
                    "event_id": "evt-gold-1",
                    "instrument_id": "GOLD",
                    "window_id": "0_30m",
                    "sampling_freq": "5m",
                    "return_raw": 0.003,
                    "return_abnormal": 0.0022,
                    "car": 0.0026,
                    "rv": 0.004,
                    "vol_change": 0.15,
                    "volume_change": 0.21,
                    "quality_flags_json": {"illiquid": False},
                    "computed_at": now.isoformat() + "Z",
                }
            ],
        )
        upsert_news_annotations(
            session,
            [
                {
                    "target_level": "event",
                    "target_id": "evt-gold-1",
                    "payload_json": {"direction_override": "positive"},
                    "author_id": "qa-user",
                    "reason": "manual adjudication",
                    "version": "v1",
                    "created_at": now.isoformat() + "Z",
                }
            ],
        )

        assert len(load_news_events(session, event_ids=["evt-gold-1"])) == 1
        assert len(load_news_event_items(session, event_ids=["evt-gold-1"])) == 1
        assert len(load_news_labels(session, target_level="event", target_ids=["evt-gold-1"])) == 1
        assert len(load_news_llm_runs(session, target_level="event", target_id="evt-gold-1")) == 1
        assert len(load_news_impact_scores(session, target_level="event", target_ids=["evt-gold-1"])) == 1
        assert len(load_news_signal_links(session, event_ids=["evt-gold-1"])) == 1
        assert len(load_event_market_reactions(session, event_ids=["evt-gold-1"])) == 1
        assert len(load_news_annotations(session, target_level="event", target_id="evt-gold-1")) == 1
