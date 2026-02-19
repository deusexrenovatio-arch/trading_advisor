from __future__ import annotations

from datetime import datetime, timedelta

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.news.gold_bootstrap import (
    backfill_event_scores_for_gold,
    bootstrap_silver_from_v2_targets,
    promote_human_labels_to_gold,
)
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_news_gold_labels,
    load_news_impact_scores,
    upsert_event_target_v2,
    upsert_news_event_items,
    upsert_news_events,
    upsert_news_impact_scores,
    upsert_news_items,
    upsert_news_labels,
)


def _settings(tmp_path) -> AppSettings:
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-gold-bootstrap.db"),
    )


def test_promote_human_labels_to_gold(tmp_path):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 1, 20, 10, 0, 0)

    with session_factory() as session:
        upsert_news_labels(
            session,
            [
                {
                    "target_level": "event",
                    "target_id": "evt-human-1",
                    "commodity_json": ["NG_US"],
                    "news_type_json": ["NG_STORAGE_EIA"],
                    "direction": "positive",
                    "magnitude": 0.8,
                    "lag_bucket": "short",
                    "relevance": 0.9,
                    "confidence": 0.85,
                    "label_source": "human",
                    "label_version": "v1",
                    "model_version": None,
                    "prompt_version": "news-v1",
                    "created_at": now.isoformat() + "Z",
                }
            ],
        )
        report = promote_human_labels_to_gold(
            session,
            source="human_hitl",
            quality="gold",
            label_schema_version="v1",
        )
        gold_rows = load_news_gold_labels(session, target_type="event", source="human_hitl")

    assert report.scanned == 1
    assert report.accepted == 1
    assert report.stored == 1
    assert len(gold_rows) == 1
    row = gold_rows[0]
    assert row["target_id"] == "evt-human-1"
    assert row["direction_label"] == "up"
    assert row["quality"] == "gold"
    assert row["event_family"] == "NG_STORAGE_EIA"


def test_bootstrap_silver_from_v2_targets_requires_model_agreement(tmp_path):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 1, 21, 9, 0, 0)

    with session_factory() as session:
        upsert_news_events(
            session,
            [
                {
                    "event_id": "evt-v2-1",
                    "event_first_published_at_utc": now.isoformat() + "Z",
                    "event_first_ingested_at_utc": now.isoformat() + "Z",
                    "event_last_published_at_utc": now.isoformat() + "Z",
                    "event_status": "active",
                    "canonical_summary": "NG storage bullish surprise",
                    "canonical_mechanism": "Storage draw tighter than expected.",
                    "cluster_version": "det-v1",
                },
                {
                    "event_id": "evt-v2-2",
                    "event_first_published_at_utc": (now + timedelta(hours=2)).isoformat() + "Z",
                    "event_first_ingested_at_utc": (now + timedelta(hours=2)).isoformat() + "Z",
                    "event_last_published_at_utc": (now + timedelta(hours=2)).isoformat() + "Z",
                    "event_status": "active",
                    "canonical_summary": "NG storage mixed",
                    "canonical_mechanism": "Mixed signal.",
                    "cluster_version": "det-v1",
                },
            ],
        )
        upsert_news_items(
            session,
            [
                {
                    "news_id": "news-v2-1",
                    "source": "fixture",
                    "url": "https://example.org/news-v2-1",
                    "title": "Storage draw larger than expected",
                    "content": "draw larger than expected",
                    "language": "en",
                    "published_at": now.isoformat() + "Z",
                    "ingested_at": now.isoformat() + "Z",
                    "hash": "hash-news-v2-1",
                },
                {
                    "news_id": "news-v2-2",
                    "source": "fixture",
                    "url": "https://example.org/news-v2-2",
                    "title": "Storage report mixed",
                    "content": "mixed report",
                    "language": "en",
                    "published_at": (now + timedelta(hours=2)).isoformat() + "Z",
                    "ingested_at": (now + timedelta(hours=2)).isoformat() + "Z",
                    "hash": "hash-news-v2-2",
                },
            ],
        )
        upsert_news_event_items(
            session,
            [
                {"event_id": "evt-v2-1", "news_id": "news-v2-1", "link_role": "primary", "similarity_score": 1.0},
                {"event_id": "evt-v2-2", "news_id": "news-v2-2", "link_role": "primary", "similarity_score": 1.0},
            ],
        )
        upsert_news_labels(
            session,
            [
                {
                    "target_level": "event",
                    "target_id": "evt-v2-1",
                    "commodity_json": ["NG_US"],
                    "news_type_json": ["NG_STORAGE_EIA"],
                    "direction": "positive",
                    "magnitude": 0.8,
                    "lag_bucket": "short",
                    "relevance": 1.0,
                    "confidence": 0.9,
                    "label_source": "rules",
                    "label_version": "v1",
                },
                {
                    "target_level": "event",
                    "target_id": "evt-v2-2",
                    "commodity_json": ["NG_US"],
                    "news_type_json": ["NG_STORAGE_EIA"],
                    "direction": "positive",
                    "magnitude": 0.8,
                    "lag_bucket": "short",
                    "relevance": 1.0,
                    "confidence": 0.9,
                    "label_source": "rules",
                    "label_version": "v1",
                },
            ],
        )
        upsert_event_target_v2(
            session,
            [
                {
                    "event_id": "evt-v2-1",
                    "symbol": "NG_US",
                    "horizon": "1h",
                    "t_pub": now.isoformat() + "Z",
                    "t_anchor": now.isoformat() + "Z",
                    "t0": now.isoformat() + "Z",
                    "t1": (now + timedelta(hours=1)).isoformat() + "Z",
                    "p0": 100.0,
                    "p1": 101.0,
                    "r_raw": 0.01,
                    "r_exp": 0.0,
                    "ar": 0.01,
                    "sigma_pre": 0.002,
                    "label_v2": 1,
                    "is_hi_conf": True,
                    "leakage_postmove": False,
                    "is_repost": False,
                    "is_overlapped": False,
                    "price_source": "mid",
                },
                {
                    "event_id": "evt-v2-2",
                    "symbol": "NG_US",
                    "horizon": "1h",
                    "t_pub": (now + timedelta(hours=2)).isoformat() + "Z",
                    "t_anchor": (now + timedelta(hours=2)).isoformat() + "Z",
                    "t0": (now + timedelta(hours=2)).isoformat() + "Z",
                    "t1": (now + timedelta(hours=3)).isoformat() + "Z",
                    "p0": 100.0,
                    "p1": 101.0,
                    "r_raw": 0.01,
                    "r_exp": 0.0,
                    "ar": 0.01,
                    "sigma_pre": 0.002,
                    "label_v2": 1,
                    "is_hi_conf": True,
                    "leakage_postmove": False,
                    "is_repost": False,
                    "is_overlapped": False,
                    "price_source": "mid",
                },
            ],
        )
        upsert_news_impact_scores(
            session,
            [
                {
                    "news_id": "news-v2-1",
                    "model_id": "finbert",
                    "model_version": "v1",
                    "direction": "up",
                    "prob_up": 0.82,
                    "prob_down": 0.08,
                    "prob_neutral": 0.10,
                    "impact_score": 0.74,
                },
                {
                    "news_id": "news-v2-1",
                    "model_id": "nli",
                    "model_version": "v1",
                    "direction": "up",
                    "prob_up": 0.78,
                    "prob_down": 0.11,
                    "prob_neutral": 0.11,
                    "impact_score": 0.69,
                },
                {
                    "news_id": "news-v2-2",
                    "model_id": "finbert",
                    "model_version": "v1",
                    "direction": "up",
                    "prob_up": 0.81,
                    "prob_down": 0.09,
                    "prob_neutral": 0.10,
                    "impact_score": 0.72,
                },
                {
                    "news_id": "news-v2-2",
                    "model_id": "nli",
                    "model_version": "v1",
                    "direction": "down",
                    "prob_up": 0.10,
                    "prob_down": 0.79,
                    "prob_neutral": 0.11,
                    "impact_score": 0.68,
                },
            ],
        )

        report = bootstrap_silver_from_v2_targets(
            session,
            horizon="1h",
            symbol="NG_US",
            min_model_confidence=0.60,
            require_both_models=True,
            require_direction_match_to_target=True,
            require_primary_news_relevance=False,
            source="auto_target_v2",
            quality="silver",
            label_schema_version="v2",
        )
        gold_rows = load_news_gold_labels(session, target_type="event", source="auto_target_v2", quality="silver")

    assert report.scanned == 2
    assert report.eligible_targets == 2
    assert report.accepted == 1
    assert report.stored == 1
    assert report.skipped_disagreement == 1
    assert len(gold_rows) == 1
    row = gold_rows[0]
    assert row["target_id"] == "evt-v2-1"
    assert row["direction_label"] == "up"
    assert row["quality"] == "silver"
    assert row["event_family"] == "NG_STORAGE_EIA"


def test_bootstrap_silver_from_v2_targets_target_only_fallback(tmp_path):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 1, 22, 12, 0, 0)

    with session_factory() as session:
        upsert_news_events(
            session,
            [
                {
                    "event_id": "evt-v2-target-only",
                    "event_first_published_at_utc": now.isoformat() + "Z",
                    "event_first_ingested_at_utc": now.isoformat() + "Z",
                    "event_last_published_at_utc": now.isoformat() + "Z",
                    "event_status": "active",
                    "canonical_summary": "target only event",
                    "canonical_mechanism": "no linked article score",
                    "cluster_version": "det-v1",
                }
            ],
        )
        upsert_news_labels(
            session,
            [
                {
                    "target_level": "event",
                    "target_id": "evt-v2-target-only",
                    "commodity_json": ["NG_US"],
                    "news_type_json": ["NG_STORAGE_EIA"],
                    "direction": "negative",
                    "magnitude": 0.8,
                    "lag_bucket": "short",
                    "relevance": 1.0,
                    "confidence": 0.9,
                    "label_source": "rules",
                    "label_version": "v1",
                }
            ],
        )
        upsert_event_target_v2(
            session,
            [
                {
                    "event_id": "evt-v2-target-only",
                    "symbol": "NG_US",
                    "horizon": "1h",
                    "t_pub": now.isoformat() + "Z",
                    "t_anchor": now.isoformat() + "Z",
                    "t0": now.isoformat() + "Z",
                    "t1": (now + timedelta(hours=1)).isoformat() + "Z",
                    "p0": 100.0,
                    "p1": 99.0,
                    "r_raw": -0.01,
                    "r_exp": 0.0,
                    "ar": -0.01,
                    "sigma_pre": 0.002,
                    "label_v2": -1,
                    "is_hi_conf": True,
                    "leakage_postmove": False,
                    "is_repost": False,
                    "is_overlapped": False,
                    "price_source": "mid",
                }
            ],
        )

        report = bootstrap_silver_from_v2_targets(
            session,
            horizon="1h",
            symbol="NG_US",
            min_model_confidence=0.60,
            require_both_models=True,
            require_direction_match_to_target=True,
            allow_no_model_scores=True,
            allow_target_only_fallback=True,
            require_primary_news_relevance=False,
            source="auto_target_v2",
            quality="silver",
            label_schema_version="v2",
        )
        gold_rows = load_news_gold_labels(session, target_type="event", source="auto_target_v2", quality="silver")

    assert report.scanned == 1
    assert report.accepted == 1
    assert report.stored == 1
    assert report.skipped_missing_scores == 0
    assert len(gold_rows) == 1
    row = gold_rows[0]
    assert row["target_id"] == "evt-v2-target-only"
    assert row["direction_label"] == "down"


def test_bootstrap_silver_from_v2_targets_impact_selector_includes_non_hi_conf(tmp_path):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 1, 22, 15, 0, 0)

    with session_factory() as session:
        upsert_news_events(
            session,
            [
                {
                    "event_id": "evt-v2-impact-only",
                    "event_first_published_at_utc": now.isoformat() + "Z",
                    "event_first_ingested_at_utc": now.isoformat() + "Z",
                    "event_last_published_at_utc": now.isoformat() + "Z",
                    "event_status": "active",
                    "canonical_summary": "Pipeline outage reduces gas supply",
                    "canonical_mechanism": "Short-term supply shock",
                    "cluster_version": "det-v1",
                }
            ],
        )
        upsert_news_items(
            session,
            [
                {
                    "news_id": "news-v2-impact-only",
                    "source": "fixture",
                    "url": "https://example.org/news-v2-impact-only",
                    "title": "Pipeline outage lifts U.S. natural gas prices",
                    "content": "Flows drop sharply after force majeure notice.",
                    "language": "en",
                    "published_at": now.isoformat() + "Z",
                    "ingested_at": now.isoformat() + "Z",
                    "hash": "hash-news-v2-impact-only",
                }
            ],
        )
        upsert_news_event_items(
            session,
            [
                {"event_id": "evt-v2-impact-only", "news_id": "news-v2-impact-only", "link_role": "primary", "similarity_score": 1.0}
            ],
        )
        upsert_news_labels(
            session,
            [
                {
                    "target_level": "event",
                    "target_id": "evt-v2-impact-only",
                    "commodity_json": ["NG_US"],
                    "news_type_json": ["INFRA_OUTAGE_PIPELINE_LNG"],
                    "direction": "positive",
                    "magnitude": 0.8,
                    "lag_bucket": "short",
                    "relevance": 1.0,
                    "confidence": 0.9,
                    "label_source": "rules",
                    "label_version": "v1",
                }
            ],
        )
        upsert_event_target_v2(
            session,
            [
                {
                    "event_id": "evt-v2-impact-only",
                    "symbol": "NG_US",
                    "horizon": "1h",
                    "t_pub": now.isoformat() + "Z",
                    "t_anchor": now.isoformat() + "Z",
                    "t0": now.isoformat() + "Z",
                    "t1": (now + timedelta(hours=1)).isoformat() + "Z",
                    "p0": 100.0,
                    "p1": 101.5,
                    "r_raw": 0.0149,
                    "r_exp": 0.0,
                    "ar": 0.0149,
                    "z_post": 2.4,
                    "impact_bin": 2,
                    "confidence": 0.82,
                    "label_v2": 1,
                    "is_hi_conf": False,
                    "leakage_postmove": False,
                    "is_repost": False,
                    "is_overlapped": False,
                    "price_source": "mid",
                }
            ],
        )
        upsert_news_impact_scores(
            session,
            [
                {
                    "news_id": "news-v2-impact-only",
                    "model_id": "finbert",
                    "model_version": "v1",
                    "direction": "up",
                    "prob_up": 0.77,
                    "prob_down": 0.12,
                    "prob_neutral": 0.11,
                    "impact_score": 0.70,
                },
                {
                    "news_id": "news-v2-impact-only",
                    "model_id": "nli",
                    "model_version": "v1",
                    "direction": "up",
                    "prob_up": 0.79,
                    "prob_down": 0.10,
                    "prob_neutral": 0.11,
                    "impact_score": 0.71,
                },
            ],
        )

        report = bootstrap_silver_from_v2_targets(
            session,
            horizon="1h",
            symbol="NG_US",
            min_model_confidence=0.60,
            source="auto_target_v2",
            quality="silver",
            label_schema_version="v2",
            target_selector="impact",
            min_target_confidence=0.70,
            min_impact_bin=1,
            min_abs_z_post=1.5,
            min_abs_ar=0.005,
        )
        gold_rows = load_news_gold_labels(session, target_type="event", source="auto_target_v2", quality="silver")

    assert report.scanned == 1
    assert report.accepted == 1
    assert report.stored == 1
    assert len(gold_rows) == 1
    assert gold_rows[0]["target_id"] == "evt-v2-impact-only"
    assert gold_rows[0]["direction_label"] == "up"


def test_bootstrap_silver_from_v2_targets_filters_low_relevance_primary_news(tmp_path):
    settings = _settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 1, 24, 9, 0, 0)

    with session_factory() as session:
        upsert_news_events(
            session,
            [
                {
                    "event_id": "evt-v2-fr",
                    "event_first_published_at_utc": now.isoformat() + "Z",
                    "event_first_ingested_at_utc": now.isoformat() + "Z",
                    "event_last_published_at_utc": now.isoformat() + "Z",
                    "event_status": "active",
                    "canonical_summary": "French-only commentary",
                    "canonical_mechanism": "generic analysis",
                    "cluster_version": "det-v1",
                }
            ],
        )
        upsert_news_items(
            session,
            [
                {
                    "news_id": "news-v2-fr",
                    "source": "fixture",
                    "url": "https://example.org/news-v2-fr",
                    "title": "Le marché de l'énergie reste volatil",
                    "content": "Analyse générale sans détail spécifique sur le gaz américain.",
                    "language": "fr",
                    "published_at": now.isoformat() + "Z",
                    "ingested_at": now.isoformat() + "Z",
                    "hash": "hash-news-v2-fr",
                }
            ],
        )
        upsert_news_event_items(
            session,
            [
                {"event_id": "evt-v2-fr", "news_id": "news-v2-fr", "link_role": "primary", "similarity_score": 1.0}
            ],
        )
        upsert_news_labels(
            session,
            [
                {
                    "target_level": "event",
                    "target_id": "evt-v2-fr",
                    "commodity_json": ["NG_US"],
                    "news_type_json": ["WEATHER_COLD_HEAT_DD"],
                    "direction": "positive",
                    "magnitude": 0.8,
                    "lag_bucket": "short",
                    "relevance": 1.0,
                    "confidence": 0.9,
                    "label_source": "rules",
                    "label_version": "v1",
                }
            ],
        )
        upsert_event_target_v2(
            session,
            [
                {
                    "event_id": "evt-v2-fr",
                    "symbol": "NG_US",
                    "horizon": "1h",
                    "t_pub": now.isoformat() + "Z",
                    "t_anchor": now.isoformat() + "Z",
                    "t0": now.isoformat() + "Z",
                    "t1": (now + timedelta(hours=1)).isoformat() + "Z",
                    "p0": 100.0,
                    "p1": 101.0,
                    "r_raw": 0.01,
                    "r_exp": 0.0,
                    "ar": 0.01,
                    "sigma_pre": 0.002,
                    "label_v2": 1,
                    "is_hi_conf": True,
                    "leakage_postmove": False,
                    "is_repost": False,
                    "is_overlapped": False,
                    "price_source": "mid",
                }
            ],
        )
        upsert_news_impact_scores(
            session,
            [
                {
                    "news_id": "news-v2-fr",
                    "model_id": "finbert",
                    "model_version": "v1",
                    "direction": "up",
                    "prob_up": 0.85,
                    "prob_down": 0.05,
                    "prob_neutral": 0.10,
                    "impact_score": 0.73,
                },
                {
                    "news_id": "news-v2-fr",
                    "model_id": "nli",
                    "model_version": "v1",
                    "direction": "up",
                    "prob_up": 0.86,
                    "prob_down": 0.04,
                    "prob_neutral": 0.10,
                    "impact_score": 0.72,
                },
            ],
        )

        report = bootstrap_silver_from_v2_targets(
            session,
            horizon="1h",
            symbol="NG_US",
            source="auto_target_v2",
            quality="silver",
            label_schema_version="v2",
        )
        gold_rows = load_news_gold_labels(session, target_type="event", source="auto_target_v2", quality="silver")

    assert report.scanned == 1
    assert report.accepted == 0
    assert report.stored == 0
    assert report.skipped_relevance == 1
    assert len(gold_rows) == 0


def test_backfill_event_scores_for_gold_uses_event_text(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    settings.news_models.enabled_models = ["finbert", "nli"]
    settings.news_models.inference_batch_size = 4
    settings.news_models.inference_text_max_chars = 400
    settings.news_models.inference_thread_cap = 1
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 1, 23, 11, 0, 0)

    captured_payloads: list[dict[str, object]] = []

    def _fake_inference(
        *,
        news_items,
        enabled_models,
        finbert_model_name,
        nli_model_name,
        model_version,
        batch_size,
        text_max_chars,
        thread_cap,
    ):
        rows = []
        for item in news_items:
            event_id = str(item.get("news_id") or "")
            text = str(item.get("text") or "")
            captured_payloads.append({"event_id": event_id, "text": text, "models": list(enabled_models)})
            if "finbert" in enabled_models:
                rows.append(
                    {
                        "news_id": event_id,
                        "model_id": "finbert",
                        "model_version": model_version,
                        "direction": "up",
                        "prob_up": 0.8,
                        "prob_down": 0.1,
                        "prob_neutral": 0.1,
                        "impact_score": 0.72,
                        "calibrated": False,
                        "inference_ts": now,
                        "score_hash": f"f-{event_id}",
                    }
                )
            if "nli" in enabled_models:
                rows.append(
                    {
                        "news_id": event_id,
                        "model_id": "nli",
                        "model_version": model_version,
                        "direction": "down",
                        "prob_up": 0.1,
                        "prob_down": 0.8,
                        "prob_neutral": 0.1,
                        "impact_score": 0.71,
                        "calibrated": False,
                        "inference_ts": now,
                        "score_hash": f"n-{event_id}",
                    }
                )
        return rows

    monkeypatch.setattr("moex_carry.news.gold_bootstrap.run_dual_model_inference_batch", _fake_inference)

    with session_factory() as session:
        upsert_news_events(
            session,
            [
                {
                    "event_id": "evt-score-1",
                    "event_first_published_at_utc": now.isoformat() + "Z",
                    "event_first_ingested_at_utc": now.isoformat() + "Z",
                    "event_last_published_at_utc": now.isoformat() + "Z",
                    "event_status": "active",
                    "canonical_summary": "Storage draw surprise",
                    "canonical_mechanism": "Supply tighter than expected",
                    "cluster_version": "det-v1",
                }
            ],
        )
        upsert_news_labels(
            session,
            [
                {
                    "target_level": "event",
                    "target_id": "evt-score-1",
                    "commodity_json": ["NG_US"],
                    "news_type_json": ["NG_STORAGE_EIA"],
                    "direction": "positive",
                    "magnitude": 0.7,
                    "lag_bucket": "short",
                    "relevance": 0.9,
                    "confidence": 0.8,
                    "label_source": "human",
                    "label_version": "v1",
                    "created_at": now.isoformat() + "Z",
                }
            ],
        )
        promote_human_labels_to_gold(session, source="human_hitl", quality="gold", label_schema_version="v1")

        report = backfill_event_scores_for_gold(
            session,
            settings,
            quality="gold",
            source="human_hitl",
            max_events=10,
        )
        scores = load_news_impact_scores(
            session,
            target_level="event",
            target_ids=["evt-score-1"],
            limit=10,
        )

    assert report.scanned_labels == 1
    assert report.candidate_events == 1
    assert report.scored_events == 1
    assert report.stored_scores == 2
    assert any("Storage draw surprise" in item["text"] for item in captured_payloads)
    models = {str(row.get("model_id") or "") for row in scores}
    assert "finbert" in models
    assert "nli" in models
