from __future__ import annotations

from datetime import datetime, timedelta

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.news.anchors import (
    link_news_to_scheduled_anchors,
    seed_canonical_scheduled_events,
    seed_episodic_anchor_events,
)
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import (
    load_news_event_items,
    load_news_event_links,
    load_news_event_updates,
    load_news_events,
    load_news_labels,
    upsert_news_entity_links,
    upsert_news_event_items,
    upsert_news_events,
    upsert_news_items,
)


def _build_settings(tmp_path):
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-anchors.db"),
    )


def test_seed_canonical_scheduled_events_is_idempotent(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        period_from = datetime(2026, 1, 1, 0, 0, 0)
        period_to = datetime(2026, 1, 31, 23, 59, 0)
        report_1 = seed_canonical_scheduled_events(
            session,
            period_from=period_from,
            period_to=period_to,
            cluster_version="anchor-test-v1",
            padding_days=0,
        )
        report_2 = seed_canonical_scheduled_events(
            session,
            period_from=period_from,
            period_to=period_to,
            cluster_version="anchor-test-v1",
            padding_days=0,
        )

        all_events = load_news_events(
            session,
            published_from=period_from.isoformat() + "Z",
            published_to=period_to.isoformat() + "Z",
            limit=0,
        )
        anchor_events = [row for row in all_events if str(row.get("cluster_version") or "") == "anchor-test-v1"]
        anchor_ids = [str(row.get("event_id") or "").strip() for row in anchor_events if row.get("event_id")]
        anchor_labels = load_news_labels(
            session,
            target_level="event",
            target_ids=anchor_ids,
            label_source="anchor_schedule",
            limit=0,
        )

    assert report_1.events_prepared > 0
    assert report_1.events_prepared == report_2.events_prepared
    assert len(anchor_events) == report_1.events_prepared
    assert len(anchor_labels) == len(anchor_events)


def test_link_news_to_scheduled_anchors_creates_crosswalk(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        period_from = datetime(2026, 2, 1, 0, 0, 0)
        period_to = datetime(2026, 2, 14, 23, 59, 0)
        seed_canonical_scheduled_events(
            session,
            period_from=period_from,
            period_to=period_to,
            cluster_version="anchor-test-v2",
            padding_days=0,
        )
        events = load_news_events(
            session,
            published_from=period_from.isoformat() + "Z",
            published_to=period_to.isoformat() + "Z",
            limit=0,
        )
        anchor_events = [row for row in events if str(row.get("cluster_version") or "") == "anchor-test-v2"]
        ng_anchor = next(
            row
            for row in anchor_events
            if "ticker=NG_US" in str(row.get("canonical_mechanism") or "")
        )
        anchor_event_id = str(ng_anchor["event_id"])
        anchor_ts = datetime.fromisoformat(str(ng_anchor["event_first_published_at_utc"]).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
        news_ts = anchor_ts + timedelta(minutes=15)
        news_id = "news-anchor-link-1"

        upsert_news_items(
            session,
            [
                {
                    "news_id": news_id,
                    "source": "fixture",
                    "url": "https://example.org/news-anchor-link-1",
                    "title": "EIA release reaction",
                    "content": "Gas reacts to scheduled release.",
                    "language": "en",
                    "published_at": news_ts.isoformat() + "Z",
                    "ingested_at": news_ts.isoformat() + "Z",
                    "hash": "hash-anchor-link-1",
                }
            ],
        )
        upsert_news_entity_links(
            session,
            [
                {
                    "news_id": news_id,
                    "entity_type": "commodity",
                    "entity_id": "NG_US",
                    "ticker": "NG_US",
                    "link_confidence": 0.99,
                    "link_stage": "fixture",
                }
            ],
        )
        upsert_news_events(
            session,
            [
                {
                    "event_id": "evt-internal-ng-1",
                    "event_first_published_at_utc": news_ts.isoformat() + "Z",
                    "event_first_ingested_at_utc": news_ts.isoformat() + "Z",
                    "event_last_published_at_utc": news_ts.isoformat() + "Z",
                    "event_status": "active",
                    "canonical_summary": "Internal cluster",
                    "canonical_mechanism": "deterministic cluster",
                    "cluster_version": "det-v1",
                }
            ],
        )
        upsert_news_event_items(
            session,
            [
                {
                    "event_id": "evt-internal-ng-1",
                    "news_id": news_id,
                    "link_role": "primary",
                    "similarity_score": 0.9,
                    "added_at": news_ts.isoformat() + "Z",
                }
            ],
        )

        report = link_news_to_scheduled_anchors(
            session,
            news_rows=[
                {
                    "news_id": news_id,
                    "published_at": news_ts.isoformat() + "Z",
                }
            ],
            cluster_version="anchor-test-v2",
            window_minutes=90,
        )
        items = load_news_event_items(session, news_ids=[news_id], limit=100)
        links = load_news_event_links(session, src_event_id=anchor_event_id, link_type="scheduled_anchor", limit=100)

    assert report.linked_news >= 1
    assert any(
        str(item.get("event_id") or "") == anchor_event_id
        and str(item.get("link_role") or "") == "scheduled_anchor"
        for item in items
    )
    assert any(
        str(item.get("dst_event_id") or "") == "evt-internal-ng-1"
        for item in links
    )


def test_seed_episodic_anchors_and_link_news(tmp_path, monkeypatch):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    class _Response:
        def __init__(self, *, status_code: int = 200, text: str = "", payload=None):
            self.status_code = status_code
            self.text = text
            self._payload = payload

        def json(self):
            if self._payload is None:
                raise ValueError("no json payload")
            return self._payload

    nhc_payload = {
        "activeStorms": [
            {
                "id": "AL012026",
                "name": "Alex",
                "lastUpdate": "2026-02-10T12:00:00Z",
                "status": "Active",
                "basin": "GOM",
            }
        ]
    }
    ukmto_html = """
    <html><body>
      <ul>
        <li><a href="/incident/123">12 Feb 2026 Incident near Bab el-Mandeb shipping lane</a></li>
      </ul>
    </body></html>
    """
    bsee_html = """
    <html><body>
      <ul>
        <li><a href="/reports/1">13 Feb 2026 Gulf production shut in due to hurricane</a></li>
      </ul>
    </body></html>
    """
    panama_html = """
    <html><body>
      <ul>
        <li><a href="/notice/1">14 Feb 2026 Advisory to Shipping: draft restriction update</a></li>
      </ul>
    </body></html>
    """
    suez_html = """
    <html><body>
      <ul>
        <li><a href="/circular/1">15 Feb 2026 Navigation Circular on transit adjustment</a></li>
      </ul>
    </body></html>
    """

    def _mock_get(url, timeout=0, **kwargs):
        if "CurrentStorms.json" in str(url):
            return _Response(status_code=200, payload=nhc_payload)
        if "ukmto.org" in str(url):
            return _Response(status_code=200, text=ukmto_html)
        if "bsee.gov" in str(url):
            return _Response(status_code=200, text=bsee_html)
        if "pancanal.com" in str(url):
            return _Response(status_code=200, text=panama_html)
        if "suezcanal.gov.eg" in str(url):
            return _Response(status_code=200, text=suez_html)
        return _Response(status_code=404)

    monkeypatch.setattr("moex_carry.news.anchors_sources.requests.get", _mock_get)

    with session_factory() as session:
        seed_report = seed_episodic_anchor_events(
            session,
            cluster_version="anchor-episodic-test-v1",
            sources=["nhc", "ukmto", "bsee", "panama", "suez"],
            timeout_sec=5,
            nhc_url="https://www.nhc.noaa.gov/CurrentStorms.json",
            ukmto_url="https://www.ukmto.org/recent-incidents",
            bsee_url="https://www.bsee.gov/resources-tools/planning-preparedness/hurricane/hurricane-history",
            panama_url="https://pancanal.com/en/maritime-services/advisory-to-shipping/",
            suez_url="https://www.suezcanal.gov.eg/English/Navigation/NavigationCirculars/Pages/default.aspx",
        )
        assert seed_report.events_stored > 0
        assert seed_report.updates_stored > 0
        assert "bsee" in seed_report.sources_completed
        assert "panama" in seed_report.sources_completed
        assert "suez" in seed_report.sources_completed

        events = load_news_events(session, limit=0)
        episodic_events = [row for row in events if str(row.get("cluster_version") or "") == "anchor-episodic-test-v1"]
        assert episodic_events

        brn_event = next(
            row
            for row in episodic_events
            if "ticker=BRN" in str(row.get("canonical_mechanism") or "")
        )
        brn_event_id = str(brn_event.get("event_id") or "")
        brn_event_ts = datetime.fromisoformat(str(brn_event.get("event_first_published_at_utc")).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
        news_ts = brn_event_ts + timedelta(minutes=30)
        upsert_news_items(
            session,
            [
                {
                    "news_id": "news-episodic-1",
                    "source": "fixture",
                    "url": "https://example.org/news-episodic-1",
                    "title": "Shipping route tension grows",
                    "content": "BRN market reacts to maritime incident.",
                    "language": "en",
                    "published_at": news_ts.isoformat() + "Z",
                    "ingested_at": news_ts.isoformat() + "Z",
                    "hash": "hash-episodic-1",
                }
            ],
        )
        upsert_news_entity_links(
            session,
            [
                {
                    "news_id": "news-episodic-1",
                    "entity_type": "commodity",
                    "entity_id": "BRN",
                    "ticker": "BRN",
                    "link_confidence": 0.98,
                    "link_stage": "fixture",
                }
            ],
        )
        link_report = link_news_to_scheduled_anchors(
            session,
            news_rows=[{"news_id": "news-episodic-1", "published_at": news_ts.isoformat() + "Z"}],
            cluster_version="anchor-episodic-test-v1",
            window_minutes=240,
            link_role="episodic_anchor",
            link_type="episodic_anchor",
        )
        event_items = load_news_event_items(session, news_ids=["news-episodic-1"], limit=100)
        updates = load_news_event_updates(session, event_ids=[brn_event_id], limit=100)

    assert link_report.linked_news >= 1
    assert any(
        str(item.get("event_id") or "") == brn_event_id
        and str(item.get("link_role") or "") == "episodic_anchor"
        for item in event_items
    )
    assert len(updates) >= 1
