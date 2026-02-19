from __future__ import annotations

from datetime import datetime, timedelta

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.news.target_v2 import _mark_overlaps, rebuild_event_target_v2
from moex_carry.storage import models as db_models
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import load_event_target_v2


def _build_settings(tmp_path):
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-target-v2.db"),
    )


def test_rebuild_event_target_v2_builds_rows(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    base = datetime(2025, 7, 1, 12, 0, 0)

    with session_factory() as session:
        session.add(
            db_models.NewsItemModel(
                news_id="news-v2-1",
                source="fixture",
                url="https://example.com/news-v2-1",
                title="Fixture v2",
                content="Storage draw surprise",
                language="en",
                published_at=base,
                ingested_at=base,
                hash="hash-news-v2-1",
            )
        )
        session.add(
            db_models.NewsEntityLinkModel(
                news_id="news-v2-1",
                entity_type="instrument",
                entity_id="AAA",
                ticker="AAA",
                link_confidence=0.9,
                link_stage="dictionary",
            )
        )
        session.add(
            db_models.NewsEventModel(
                event_id="evt-v2-1",
                event_first_published_at_utc=base,
                event_first_ingested_at_utc=base,
                event_last_published_at_utc=base,
                event_status="active",
                canonical_summary="Fixture event",
                canonical_mechanism="scheduled_anchor|event_family=NG_STORAGE_EIA",
                cluster_version="det-v1",
                created_at=base,
                updated_at=base,
            )
        )
        session.add(
            db_models.NewsEventItemModel(
                event_id="evt-v2-1",
                news_id="news-v2-1",
                link_role="primary",
                similarity_score=1.0,
                added_at=base,
            )
        )
        session.add(
            db_models.NewsLabelModel(
                label_id="lbl-v2-1",
                target_level="event",
                target_id="evt-v2-1",
                commodity_json=["AAA"],
                market_scope="futures",
                instrument_candidates_json=[],
                relevance=1.0,
                news_type_json=["NG_STORAGE_EIA"],
                direction="positive",
                magnitude=0.8,
                lag_bucket="short",
                confidence=0.9,
                uncertainty_type="none",
                geo_scope="US",
                evidence_json={"event_family": "NG_STORAGE_EIA"},
                label_source="rules",
                label_version="v1",
                model_version=None,
                prompt_version=None,
                created_at=base,
            )
        )
        for i in range(-180, 240):
            ts = base + timedelta(minutes=i)
            price = 100.0 + 0.01 * float(i)
            session.add(
                db_models.QuoteModel(
                    secid="AAA",
                    timestamp=ts,
                    bid=price - 0.05,
                    ask=price + 0.05,
                    last=price,
                    volume=1000.0,
                )
            )
        session.commit()

        report = rebuild_event_target_v2(
            session,
            horizon="1h",
            symbol="AAA",
            published_from=base - timedelta(days=1),
            published_to=base + timedelta(days=1),
            processing_lag_sec=60,
            max_events=0,
            use_midpoint=True,
        )

        assert report.events_seen >= 1
        assert report.rows_upserted >= 1

        rows = load_event_target_v2(
            session,
            event_ids=["evt-v2-1"],
            symbol="AAA",
            horizon="1h",
            clean_only=False,
            limit=100,
        )
        assert len(rows) >= 1
        first = rows[0]
        assert first["horizon"] == "1h"
        assert first["symbol"] == "AAA"
        assert first["label_v2"] in {-1, 0, 1}
        assert first["impact_bin"] in {0, 1, 2}
        assert float(first["impact_score"] or 0.0) >= 0.0
        assert float(first["sigma_hat"] or 0.0) > 0.0
        assert first["event_time_source"] in {"first_seen", "published"}
        assert first["t_event"] is not None
        assert first["t0"] is not None
        assert first["t1"] is not None

        session.add(
            db_models.EventTargetV2Model(
                event_id="evt-v2-stale",
                symbol="AAA",
                horizon="1h",
                t_pub=base,
                t_anchor=base,
                t_event=base,
                event_time_source="published",
                t0=base,
                t1=base + timedelta(hours=1),
                p0=100.0,
                p1=101.0,
                r_raw=0.01,
                r_exp=0.0,
                ar=0.01,
                sigma_pre=0.01,
                label_v2=1,
                is_hi_conf=False,
                leakage_postmove=False,
                is_repost=False,
                is_overlapped=False,
                price_source="mid",
                created_at=base,
                updated_at=base,
            )
        )
        session.commit()

        rerun = rebuild_event_target_v2(
            session,
            horizon="1h",
            symbol="AAA",
            published_from=base - timedelta(days=1),
            published_to=base + timedelta(days=1),
            processing_lag_sec=60,
            max_events=0,
            use_midpoint=True,
        )
        assert rerun.rows_deleted >= 1
        stale_rows = load_event_target_v2(
            session,
            event_ids=["evt-v2-stale"],
            symbol="AAA",
            horizon="1h",
            clean_only=False,
            limit=100,
        )
        assert stale_rows == []


def test_mark_overlaps_collapses_same_episode_updates():
    base = datetime(2026, 1, 25, 10, 0, 0)
    rows = [
        {
            "event_id": "evt-1",
            "symbol": "NG_US",
            "horizon": "1h",
            "_t0_dt": base,
            "_t1_dt": base + timedelta(minutes=60),
            "_episode_key": "storm:alpha",
        },
        {
            "event_id": "evt-2",
            "symbol": "NG_US",
            "horizon": "1h",
            "_t0_dt": base + timedelta(minutes=10),
            "_t1_dt": base + timedelta(minutes=70),
            "_episode_key": "storm:alpha",
        },
        {
            "event_id": "evt-3",
            "symbol": "NG_US",
            "horizon": "1h",
            "_t0_dt": base + timedelta(minutes=15),
            "_t1_dt": base + timedelta(minutes=75),
            "_episode_key": "family:ng_storage_eia",
        },
    ]

    overlap_rows = _mark_overlaps(rows)

    assert overlap_rows == 1
    assert rows[0]["is_overlapped"] is False
    assert rows[1]["is_overlapped"] is False
    assert rows[2]["is_overlapped"] is True
    assert rows[1]["overlap_count"] == 0
    assert rows[2]["overlap_count"] == 2
