from __future__ import annotations

from datetime import datetime

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig, UiConfig
from moex_carry.news.sync import sync_news_runtime
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import load_news_entity_links


def _build_settings(tmp_path):
    settings = AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-sync-profile.db"),
        ui=UiConfig(ff_news_bridge_enabled=True, ff_news_model_advisory_enabled=False),
    )
    settings.news_ingest.enabled = True
    settings.news_ingest.max_items_per_run = 10
    settings.news_ingest.rss_urls = []
    settings.news_ingest.commodity_profiles = [
        settings.news_ingest.CommodityProfile(
            ticker="BRN",
            name="Brent",
            gdelt_query='("brent")',
            rss_urls=["https://example.org/rss/brent"],
            price_source="fred",
            price_symbol="DCOILBRENTEU",
        )
    ]
    return settings


def test_sync_uses_source_profile_mapping(tmp_path, monkeypatch):
    settings = _build_settings(tmp_path)
    now = datetime.utcnow().replace(microsecond=0)

    def _mock_fetch(urls, *, max_items):
        assert "https://example.org/rss/brent" in urls
        return [
            {
                "news_id": "news-source-profile-1",
                "source": "https://example.org/rss/brent",
                "url": "https://example.org/news/1",
                "title": "Brent market update",
                "content": "Brent crude supply cut.",
                "language": "en",
                "published_at": now.isoformat() + "Z",
                "ingested_at": now.isoformat() + "Z",
                "hash": "hash-source-profile-1",
            }
        ]

    monkeypatch.setattr("moex_carry.news.sync.fetch_rss_news", _mock_fetch)

    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        snapshot = sync_news_runtime(
            session,
            settings,
            enable_ingest=True,
            enable_inference=False,
            gate_enabled=False,
            recent_limit=20,
        )
        entity_links = load_news_entity_links(session, news_ids=["news-source-profile-1"], limit=50)

    assert snapshot.ingested_count >= 1
    assert snapshot.event_link_count >= 1
    assert snapshot.cluster_version == "det-v1"
    assert any(str(row.get("ticker") or "") == "BRN" for row in entity_links)
    assert any(str(row.get("link_stage") or "") == "source_profile" for row in entity_links)
