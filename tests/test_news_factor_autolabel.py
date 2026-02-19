from __future__ import annotations

from datetime import datetime

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.news.factor_autolabel import run_factor_autolabel_v2
from moex_carry.storage import models as db_models
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_event_factor_scores_v2,
    load_news_labels,
    upsert_event_target_v2,
)


def _build_settings(tmp_path):
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-factor-autolabel.db"),
    )


def test_run_factor_autolabel_v2_builds_scores_and_event_label(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    ts = datetime(2026, 2, 10, 15, 30, 0)

    with session_factory() as session:
        session.add(
            db_models.NewsItemModel(
                news_id="news-ng-factor-1",
                source="fixture",
                url="https://example.com/news-ng-factor-1",
                title="Colder weather boosts gas demand",
                content="Forecast turns colder with higher HDD and storage draw surprise.",
                language="en",
                published_at=ts,
                ingested_at=ts,
                hash="hash-news-ng-factor-1",
            )
        )
        session.add(
            db_models.NewsEventModel(
                event_id="evt-ng-factor-1",
                event_first_published_at_utc=ts,
                event_first_ingested_at_utc=ts,
                event_last_published_at_utc=ts,
                event_status="active",
                canonical_summary="US weather shock lifts heating demand",
                canonical_mechanism="weather demand impulse for natural gas",
                cluster_version="det-v1",
                created_at=ts,
                updated_at=ts,
            )
        )
        session.add(
            db_models.NewsEventItemModel(
                event_id="evt-ng-factor-1",
                news_id="news-ng-factor-1",
                link_role="primary",
                similarity_score=1.0,
                added_at=ts,
            )
        )
        upsert_event_target_v2(
            session,
            [
                {
                    "event_id": "evt-ng-factor-1",
                    "symbol": "NG_US",
                    "horizon": "5m",
                    "t_pub": ts.isoformat() + "Z",
                    "t_anchor": ts.isoformat() + "Z",
                    "t_event": ts.isoformat() + "Z",
                    "event_time_source": "published",
                    "t0": ts.isoformat() + "Z",
                    "t1": ts.isoformat() + "Z",
                    "p0": 2.10,
                    "p1": 2.14,
                    "r_raw": 0.0188,
                    "r_post": 0.0188,
                    "r_pre": 0.0040,
                    "r_exp": 0.0020,
                    "ar": 0.0168,
                    "sigma_pre": 0.0040,
                    "sigma_hat": 0.0080,
                    "z_post": 2.35,
                    "z_pre": 0.50,
                    "z_hold": 0.90,
                    "z_big": 1.80,
                    "impact_bin": 2,
                    "impact_score": 1.20,
                    "overlap_count": 0,
                    "echo_score": 0.0,
                    "premove_penalty": 1.0,
                    "confidence": 0.82,
                    "label_v2": 1,
                    "is_hi_conf": True,
                    "leakage_postmove": False,
                    "is_repost": False,
                    "is_overlapped": False,
                    "price_source": "last",
                }
            ],
        )

        report = run_factor_autolabel_v2(
            session,
            horizon="5m",
            symbol="NG_US",
            from_ts=datetime(2026, 2, 1, 0, 0, 0),
            to_ts=datetime(2026, 2, 20, 0, 0, 0),
            min_confidence=0.2,
            top_k=3,
            nli_enabled=False,
        )

        assert report.events_seen >= 1
        assert report.events_scored >= 1
        assert report.factor_rows_upserted >= 1
        assert report.labels_upserted >= 1

        factor_rows = load_event_factor_scores_v2(session, event_id="evt-ng-factor-1", symbol="NG_US", limit=20)
        assert len(factor_rows) >= 1
        factor_names = {str(row.get("factor_name") or "") for row in factor_rows}
        assert "WEATHER_HDD_CDD" in factor_names or "EIA_STORAGE" in factor_names

        labels = load_news_labels(
            session,
            target_level="event",
            target_ids=["evt-ng-factor-1"],
            label_source="auto_factor_v2",
            limit=20,
        )
        assert len(labels) >= 1
        label = labels[0]
        assert isinstance(label.get("news_type_json"), list)
        assert len(label["news_type_json"]) >= 1
        assert label.get("direction") in {"positive", "negative", "uncertain"}

