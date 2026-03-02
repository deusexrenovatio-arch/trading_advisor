from __future__ import annotations

from datetime import datetime

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig, UiConfig
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    upsert_event_market_reactions,
    upsert_news_entity_links,
    upsert_news_event_items,
    upsert_news_events,
    upsert_news_impact_scores,
    upsert_news_items,
    upsert_news_labels,
    upsert_news_llm_runs,
    upsert_news_signal_links,
)
from moex_carry.ui.app import create_app


def _settings(tmp_path):
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-stage-a-api.db"),
        ui=UiConfig(ff_news_bridge_enabled=True, ff_news_model_advisory_enabled=True),
    )


def _seed_event_runtime(session, *, score_target_level: str = "event"):
    ts = datetime(2026, 1, 15, 9, 0, 0)
    upsert_news_items(
        session,
        [
            {
                "news_id": "news-evt-1",
                "source": "Reuters",
                "url": "https://example.org/news-evt-1",
                "title": "Unexpected export cut supports oil",
                "content": "Export restrictions reduce available barrels.",
                "language": "en",
                "published_at": ts.isoformat() + "Z",
                "ingested_at": ts.isoformat() + "Z",
                "hash": "hash-news-evt-1",
            }
        ],
    )
    upsert_news_entity_links(
        session,
        [
            {
                "news_id": "news-evt-1",
                "entity_type": "instrument",
                "entity_id": "BRENT",
                "ticker": "BRENT",
                "link_confidence": 0.93,
                "link_stage": "dictionary",
            }
        ],
    )
    upsert_news_events(
        session,
        [
            {
                "event_id": "evt-1",
                "event_first_published_at_utc": ts.isoformat() + "Z",
                "event_first_ingested_at_utc": ts.isoformat() + "Z",
                "event_last_published_at_utc": ts.isoformat() + "Z",
                "event_status": "active",
                "canonical_summary": "Export cut in key region",
                "canonical_mechanism": "Less supply supports near-term futures curve.",
                "cluster_version": "v1",
            }
        ],
    )
    upsert_news_event_items(
        session,
        [
            {
                "event_id": "evt-1",
                "news_id": "news-evt-1",
                "link_role": "primary",
                "similarity_score": 0.99,
                "added_at": ts.isoformat() + "Z",
            }
        ],
    )
    upsert_news_labels(
        session,
        [
            {
                "target_level": "event",
                "target_id": "evt-1",
                "commodity_json": ["BRENT"],
                "news_type_json": ["SUP_DEC"],
                "direction": "positive",
                "magnitude": 0.9,
                "lag_bucket": "immediate",
                "relevance": 0.92,
                "confidence": 0.88,
                "label_source": "model",
                "label_version": "v1",
                "model_version": "finbert-v1",
            }
        ],
    )
    target_level = score_target_level.strip().lower()
    score_target_id = "evt-1" if target_level == "event" else "news-evt-1"
    upsert_news_impact_scores(
        session,
        [
            {
                "news_id": "news-evt-1",
                "target_level": target_level,
                "target_id": score_target_id,
                "model_id": "finbert",
                "model_version": "v1",
                "direction": "up",
                "prob_up": 0.85,
                "prob_down": 0.05,
                "prob_neutral": 0.10,
                "impact_score": 0.82,
                "inference_ts": ts.isoformat() + "Z",
            }
        ],
    )
    upsert_news_llm_runs(
        session,
        [
            {
                "target_level": "event",
                "target_id": "evt-1",
                "provider": "openai",
                "model_id": "gpt-5",
                "prompt_version": "news-v1",
                "status": "done",
                "token_in": 260,
                "token_out": 52,
                "latency_ms": 1200,
                "created_at": ts.isoformat() + "Z",
            }
        ],
    )
    upsert_event_market_reactions(
        session,
        [
            {
                "event_id": "evt-1",
                "instrument_id": "BRENT",
                "window_id": "0_30m",
                "sampling_freq": "5m",
                "return_raw": 0.004,
                "return_abnormal": 0.003,
                "car": 0.0032,
                "rv": 0.006,
                "vol_change": 0.12,
                "volume_change": 0.19,
                "quality_flags_json": {"overlap_event": False},
                "computed_at": ts.isoformat() + "Z",
            }
        ],
    )
    upsert_news_signal_links(
        session,
        [
            {
                "link_id": "lnk-evt-1",
                "event_id": "evt-1",
                "news_id": "news-evt-1",
                "signal_id": "sig-evt-1",
                "decision_id": "dec-evt-1",
                "link_type": "used_in_decision",
                "gate_action": "allow",
                "window_start": ts.isoformat() + "Z",
                "window_end": ts.isoformat() + "Z",
            }
        ],
    )


def test_stage_a_news_api_endpoints(tmp_path):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_event_runtime(session)

    app = create_app(settings)
    client = app.server.test_client()

    events_resp = client.get("/api/v2/events?limit=10")
    assert events_resp.status_code == 200
    events_rows = events_resp.get_json()
    assert isinstance(events_rows, list)
    assert events_rows[0]["event_id"] == "evt-1"

    fragmentation_resp = client.get("/api/v2/events/fragmentation")
    assert fragmentation_resp.status_code == 200
    fragmentation_payload = fragmentation_resp.get_json()
    assert fragmentation_payload["events_total"] >= 1
    assert fragmentation_payload["event_links_total"] >= 1
    assert "fragmentation_ratio" in fragmentation_payload

    event_resp = client.get("/api/v2/events/evt-1")
    assert event_resp.status_code == 200
    event_payload = event_resp.get_json()
    assert event_payload["event_id"] == "evt-1"
    assert len(event_payload["news_items"]) == 1
    assert len(event_payload["llm_runs"]) >= 1
    assert len(event_payload["model_scores"]) >= 1

    reaction_resp = client.get("/api/v2/events/evt-1/reaction?window_id=0_30m")
    assert reaction_resp.status_code == 200
    reaction_payload = reaction_resp.get_json()
    assert reaction_payload["event_id"] == "evt-1"
    assert len(reaction_payload["rows"]) == 1

    feed_resp = client.get("/api/v2/news/feed?limit=5")
    assert feed_resp.status_code == 200
    feed_rows = feed_resp.get_json()
    assert isinstance(feed_rows, list)
    assert feed_rows[0]["news_event_id"] == "evt-1"
    assert feed_rows[0]["llm_status"] == "done"

    top_resp = client.get("/api/v2/signals/top?commodity=BRENT&k=3")
    assert top_resp.status_code == 200
    top_rows = top_resp.get_json()
    assert isinstance(top_rows, list)
    assert top_rows[0]["news_event_id"] == "evt-1"

    ann_resp = client.post(
        "/api/v2/annotations",
        json={
            "target_level": "event",
            "target_id": "evt-1",
            "payload": {"override": "keep positive"},
            "author_id": "qa",
            "reason": "manual check",
            "version": "v1",
        },
    )
    assert ann_resp.status_code == 200
    ann_payload = ann_resp.get_json()
    assert ann_payload["status"] == "ok"
    assert ann_payload["stored"] == 1

    versions_resp = client.get("/api/v2/models/versions")
    assert versions_resp.status_code == 200
    versions_payload = versions_resp.get_json()
    assert isinstance(versions_payload.get("local_models"), list)
    assert isinstance(versions_payload.get("llm_models"), list)

    summary_resp = client.get("/api/v2/validation/summary")
    assert summary_resp.status_code == 200
    summary_payload = summary_resp.get_json()
    assert summary_payload["events_total"] >= 1
    assert summary_payload["llm_runs_total"] >= 1

    event_study_resp = client.get("/api/v2/validation/event-study?commodity=BRENT&window_id=0_30m")
    assert event_study_resp.status_code == 200
    study_payload = event_study_resp.get_json()
    assert study_payload["sample_count"] >= 1
    assert "car_summary_by_direction" in study_payload


def test_stage_a_news_feed_derives_event_scores_from_news_level(tmp_path):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        _seed_event_runtime(session, score_target_level="news")

    app = create_app(settings)
    client = app.server.test_client()
    feed_resp = client.get("/api/v2/news/feed?limit=5")
    assert feed_resp.status_code == 200
    feed_rows = feed_resp.get_json()
    assert isinstance(feed_rows, list)
    assert len(feed_rows) >= 1

    first = feed_rows[0]
    assert first["news_event_id"] == "evt-1"
    model_scores = first["model_scores"]
    assert isinstance(model_scores, list)
    assert len(model_scores) >= 1
    primary = model_scores[0]
    assert primary["target_level"] == "event"
    assert primary["target_id"] == "evt-1"
    assert primary["derived_from"] == "news_items"
    assert primary["direction"] in {"up", "down", "neutral"}
