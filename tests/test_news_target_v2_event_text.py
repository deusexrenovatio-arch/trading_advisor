from __future__ import annotations

from datetime import datetime, timedelta

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.news.target_v2_event_text import build_event_echo_scores
from moex_carry.storage import models as db_models
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db


def _build_settings(tmp_path):
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-target-v2-event-text.db"),
    )


def test_build_event_echo_scores_accepts_iso_published_at_strings(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    base = datetime(2026, 1, 10, 10, 0, 0)

    with session_factory() as session:
        session.add(
            db_models.NewsItemModel(
                news_id="n-echo-1",
                source="reuters",
                url="https://example.com/echo-1",
                title="Primary source report",
                content="Initial report content",
                language="en",
                published_at=base,
                ingested_at=base,
                hash="hash-echo-1",
            )
        )
        session.add(
            db_models.NewsItemModel(
                news_id="n-echo-2",
                source="analysis.blog",
                url="https://example.com/echo-2",
                title="Follow-up commentary",
                content="Follow-up commentary content",
                language="en",
                published_at=base + timedelta(minutes=90),
                ingested_at=base + timedelta(minutes=90),
                hash="hash-echo-2",
            )
        )
        session.commit()

        scores = build_event_echo_scores(
            session,
            event_to_news={"evt-echo": ["n-echo-1", "n-echo-2"]},
            delay_minutes=45,
        )

    assert "evt-echo" in scores
    assert float(scores["evt-echo"]) > 0.0
