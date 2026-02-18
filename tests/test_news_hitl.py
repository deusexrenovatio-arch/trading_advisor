from __future__ import annotations

from datetime import datetime

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.news.hitl import (
    apply_news_hitl_labels,
    build_news_hitl_tasks,
    export_news_hitl_tasks,
    load_hitl_label_rows,
    summarize_news_hitl_state,
)
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_news_annotations,
    load_news_labels,
    upsert_news_entity_links,
    upsert_news_event_items,
    upsert_news_events,
    upsert_news_impact_scores,
    upsert_news_items,
)


def _build_settings(tmp_path):
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-hitl.db"),
    )


def _seed_hitl_fixture(session) -> None:
    now = datetime(2026, 2, 18, 12, 0, 0)
    upsert_news_items(
        session,
        [
            {
                "news_id": "news-ng-1",
                "source": "fixture",
                "url": "https://example.org/ng-1",
                "title": "Gas storage draw larger than expected",
                "content": "Potential upside pressure in Henry Hub futures.",
                "language": "en",
                "published_at": now.isoformat() + "Z",
                "ingested_at": now.isoformat() + "Z",
                "hash": "hash-ng-1",
            },
            {
                "news_id": "news-ng-2",
                "source": "fixture",
                "url": "https://example.org/ng-2",
                "title": "Mild weather outlook lowers heating demand",
                "content": "Could pressure natural gas prices lower.",
                "language": "en",
                "published_at": now.isoformat() + "Z",
                "ingested_at": now.isoformat() + "Z",
                "hash": "hash-ng-2",
            },
        ],
    )
    upsert_news_events(
        session,
        [
            {
                "event_id": "evt-ng-1",
                "event_first_published_at_utc": now.isoformat() + "Z",
                "event_first_ingested_at_utc": now.isoformat() + "Z",
                "event_status": "active",
                "canonical_summary": "Storage draw surprise",
                "canonical_mechanism": "Tighter inventory supports futures",
                "cluster_version": "det-v1",
            },
            {
                "event_id": "evt-ng-2",
                "event_first_published_at_utc": now.isoformat() + "Z",
                "event_first_ingested_at_utc": now.isoformat() + "Z",
                "event_status": "active",
                "canonical_summary": "Warm forecast",
                "canonical_mechanism": "Lower demand expectations",
                "cluster_version": "det-v1",
            },
        ],
    )
    upsert_news_event_items(
        session,
        [
            {"event_id": "evt-ng-1", "news_id": "news-ng-1", "link_role": "primary"},
            {"event_id": "evt-ng-2", "news_id": "news-ng-2", "link_role": "primary"},
        ],
    )
    upsert_news_entity_links(
        session,
        [
            {
                "news_id": "news-ng-1",
                "entity_type": "commodity",
                "entity_id": "NG_US",
                "ticker": "NG_US",
                "link_confidence": 0.98,
                "link_stage": "source_profile",
            },
            {
                "news_id": "news-ng-2",
                "entity_type": "commodity",
                "entity_id": "GOLD",
                "ticker": "GOLD",
                "link_confidence": 0.98,
                "link_stage": "source_profile",
            },
        ],
    )
    upsert_news_impact_scores(
        session,
        [
            {
                "news_id": "news-ng-1",
                "model_id": "finbert",
                "model_version": "v1",
                "direction": "up",
                "prob_up": 0.80,
                "prob_down": 0.10,
                "prob_neutral": 0.10,
                "impact_score": 0.70,
                "inference_ts": now.isoformat() + "Z",
            },
            {
                "news_id": "news-ng-2",
                "model_id": "finbert",
                "model_version": "v1",
                "direction": "down",
                "prob_up": 0.15,
                "prob_down": 0.70,
                "prob_neutral": 0.15,
                "impact_score": 0.55,
                "inference_ts": now.isoformat() + "Z",
            },
        ],
    )


def test_news_hitl_export_and_import_roundtrip(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        _seed_hitl_fixture(session)
        tasks = build_news_hitl_tasks(
            session,
            settings,
            max_items=2,
            min_impact=0.0,
            only_unlabeled=True,
        )
        assert len(tasks) == 2
        assert tasks[0].event_id == "evt-ng-1"
        ng_only = build_news_hitl_tasks(
            session,
            settings,
            max_items=5,
            min_impact=0.0,
            only_unlabeled=True,
            ticker="NG_US",
        )
        assert len(ng_only) == 1
        assert ng_only[0].event_id == "evt-ng-1"
        state_before = summarize_news_hitl_state(session)
        assert int(state_before["human_labels_total"]) == 0

    output_path = tmp_path / "news_hitl_tasks.jsonl"
    exported = export_news_hitl_tasks(tasks=tasks, output_path=output_path, output_format="jsonl")
    assert exported.exists()
    loaded = load_hitl_label_rows(exported)
    assert len(loaded) == 2

    manual_rows = [
        {
            "event_id": "evt-ng-1",
            "label": {
                "commodity": ["NG_US"],
                "market_scope": "futures",
                "instrument_candidates": [{"symbol": "NG=F", "exchange": "NYMEX"}],
                "relevance": 0.92,
                "news_type": ["SUP_DEC"],
                "direction": "positive",
                "magnitude": 0.75,
                "lag_bucket": "short",
                "confidence": 0.83,
                "uncertainty_type": "none",
                "geo_scope": "US",
                "evidence_spans": [{"text": "inventory draw larger than expected"}],
            },
        }
    ]

    with session_factory() as session:
        report = apply_news_hitl_labels(
            session,
            label_rows=manual_rows,
            author_id="qa",
            reason="manual",
            label_version="v1",
            prompt_version="news-v1",
        )
        assert int(report["labels_stored"]) == 1
        assert int(report["annotations_stored"]) == 1
        labels = load_news_labels(session, target_level="event", target_ids=["evt-ng-1"], label_source="human")
        assert len(labels) == 1
        assert labels[0]["direction"] == "positive"
        annotations = load_news_annotations(session, target_level="event", target_id="evt-ng-1")
        assert len(annotations) >= 1
