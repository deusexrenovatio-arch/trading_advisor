from __future__ import annotations

from datetime import date, datetime, timedelta

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig, UiConfig
from moex_carry.news.backfill import _fetch_yfinance_series, _shock_score_by_window, run_news_backfill, run_news_qc
from moex_carry.news.ingestion import fetch_newsapi_news
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db
from moex_carry.storage.repositories import load_news_entity_links, load_news_items, upsert_news_items, upsert_quotes


def _build_settings(tmp_path):
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-backfill.db"),
        ui=UiConfig(ff_news_bridge_enabled=True, ff_news_model_advisory_enabled=True),
    )


def test_news_backfill_populates_links_and_quotes(tmp_path, monkeypatch):
    settings = _build_settings(tmp_path)
    settings.news_ingest.qc_min_news_per_ticker = 1
    settings.news_ingest.qc_min_price_points_per_ticker = 1
    settings.news_ingest.backfill_chunk_days = 3
    settings.news_ingest.backfill_max_windows_per_commodity = 2

    def _mock_gdelt_news(*, query, start_dt, end_dt, **_kwargs):
        marker = str(start_dt.date())
        news_id = f"news-{abs(hash((query, marker))) % 1000000:06d}"
        return [
            {
                "news_id": news_id,
                "source": "gdelt",
                "url": f"https://example.org/{news_id}",
                "title": f"{query} headline",
                "content": "supply cut supports price",
                "language": "en",
                "published_at": start_dt.isoformat().replace("+00:00", "Z"),
                "ingested_at": (start_dt + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "hash": f"hash-{news_id}",
            }
        ]

    def _mock_price_rows(*, profile, period_from, period_to, timeout_sec):
        rows = []
        cursor = datetime.combine(period_from, datetime.min.time())
        end_dt = datetime.combine(period_to, datetime.min.time())
        while cursor <= end_dt:
            rows.append(
                {
                    "secid": str(profile.ticker),
                    "timestamp": cursor.isoformat() + "Z",
                    "last": 100.0,
                    "bid": None,
                    "ask": None,
                    "volume": None,
                }
            )
            cursor += timedelta(days=1)
        return rows

    monkeypatch.setattr("moex_carry.news.backfill.fetch_gdelt_news", _mock_gdelt_news)
    monkeypatch.setattr("moex_carry.news.backfill._fetch_price_rows_for_profile", _mock_price_rows)

    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        report = run_news_backfill(
            session,
            settings,
            period_from=date(2025, 1, 1),
            period_to=date(2025, 1, 10),
            commodities=["BRN", "GOLD"],
            include_prices=True,
            run_inference=False,
        )

    assert report.ingested_count > 0
    assert report.entity_link_count > 0
    assert report.quote_count > 0
    assert report.qc_report["passed"] is True
    tickers = {item["ticker"] for item in report.qc_report["commodities"]}
    assert {"BRN", "GOLD"}.issubset(tickers)


def test_news_qc_reports_missing_data(tmp_path):
    settings = _build_settings(tmp_path)
    settings.news_ingest.qc_min_news_per_ticker = 1
    settings.news_ingest.qc_min_price_points_per_ticker = 1

    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        report = run_news_qc(
            session,
            settings,
            period_from=date(2025, 1, 1),
            period_to=date(2025, 1, 31),
            commodities=["NG_US"],
        )

    assert report["passed"] is False
    assert report["commodities"][0]["ticker"] == "NG_US"


def test_fetch_yfinance_series_handles_multiindex(monkeypatch):
    import pandas as pd

    index = pd.to_datetime(
        [
            "2025-01-01T10:00:00Z",
            "2025-01-01T11:00:00Z",
        ],
        utc=True,
    )
    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "GC=F"),
            ("Volume", "GC=F"),
        ],
        names=["Price", "Ticker"],
    )
    frame = pd.DataFrame(
        [
            [2010.5, 1200.0],
            [2011.0, 950.0],
        ],
        index=index,
        columns=columns,
    )

    class _FakeYFinance:
        @staticmethod
        def download(*_args, **_kwargs):
            return frame

    monkeypatch.setattr("moex_carry.news.backfill.importlib.import_module", lambda _name: _FakeYFinance)

    rows = _fetch_yfinance_series(
        symbol="GC=F",
        interval="60m",
        period_from=date(2025, 1, 1),
        period_to=date(2025, 1, 1),
    )

    assert len(rows) == 2
    assert rows[0]["last"] == 2010.5
    assert rows[0]["volume"] == 1200.0
    assert str(rows[0]["timestamp"]).endswith("Z")


def test_fetch_newsapi_news_normalizes_payload(monkeypatch):
    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "status": "ok",
                "articles": [
                    {
                        "source": {"id": None, "name": "Reuters"},
                        "title": "Natural gas rises on freeze-offs",
                        "description": "Weather drives demand.",
                        "content": "Freeze-offs reduce supply.",
                        "url": "https://example.org/news/ng-1",
                        "publishedAt": "2026-01-21T10:00:00Z",
                    }
                ],
            }

    monkeypatch.setattr("moex_carry.news.ingestion.requests.get", lambda *args, **kwargs: _FakeResponse())

    rows = fetch_newsapi_news(
        query="natural gas",
        start_dt=datetime(2026, 1, 21),
        end_dt=datetime(2026, 1, 22),
        api_key="test-key",
    )

    assert len(rows) == 1
    assert str(rows[0]["source"]).startswith("newsapi:")
    assert rows[0]["title"] == "Natural gas rises on freeze-offs"
    assert str(rows[0]["published_at"]).endswith("Z")


def test_news_backfill_respects_newsapi_daily_budget(tmp_path, monkeypatch):
    settings = _build_settings(tmp_path)
    settings.news_ingest.gdelt_enabled = False
    settings.news_ingest.newsapi_enabled = True
    settings.news_ingest.newsapi_api_key = "test-key"
    settings.news_ingest.newsapi_daily_limit = 2
    settings.news_ingest.newsapi_daily_state_path = str(tmp_path / "newsapi_usage.json")
    settings.news_ingest.newsapi_backfill_max_pages_per_window = 1
    settings.news_ingest.newsapi_max_records_per_call = 5
    settings.news_ingest.backfill_chunk_days = 1
    settings.news_ingest.backfill_max_windows_per_commodity = 0
    settings.news_ingest.qc_min_news_per_ticker = 1
    settings.news_ingest.qc_min_price_points_per_ticker = 0

    def _mock_newsapi_news(*, query, start_dt, end_dt, **_kwargs):
        marker = str(start_dt.date())
        news_id = f"news-newsapi-{abs(hash((query, marker))) % 1000000:06d}"
        return [
            {
                "news_id": news_id,
                "source": "newsapi:test",
                "url": f"https://example.org/{news_id}",
                "title": f"{query} headline",
                "content": "weather drives demand",
                "language": "en",
                "published_at": start_dt.isoformat().replace("+00:00", "Z"),
                "ingested_at": (start_dt + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "hash": f"hash-{news_id}",
            }
        ]

    monkeypatch.setattr("moex_carry.news.backfill.fetch_newsapi_news", _mock_newsapi_news)

    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        report = run_news_backfill(
            session,
            settings,
            period_from=date(2026, 1, 1),
            period_to=date(2026, 1, 3),
            commodities=["NG_US"],
            include_prices=False,
            run_inference=False,
        )

    assert report.newsapi_requests_used == 2
    assert report.newsapi_requests_remaining == 0
    assert report.ingested_count == 2


def test_news_backfill_does_not_force_profile_ticker_without_support(tmp_path, monkeypatch):
    settings = _build_settings(tmp_path)
    settings.news_ingest.qc_min_news_per_ticker = 0
    settings.news_ingest.qc_min_price_points_per_ticker = 0
    settings.news_ingest.backfill_chunk_days = 1
    settings.news_ingest.backfill_max_windows_per_commodity = 1

    def _mock_gdelt_news(*, query, start_dt, end_dt, **_kwargs):
        return [
            {
                "news_id": "news-unrelated-profile",
                "source": "gdelt",
                "url": "https://example.org/unrelated-profile",
                "title": "India and UAE sign new defense pact",
                "content": "Bilateral cooperation in transport and defense industries.",
                "language": "en",
                "published_at": start_dt.isoformat().replace("+00:00", "Z"),
                "ingested_at": (start_dt + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "hash": "hash-unrelated-profile",
            }
        ]

    monkeypatch.setattr("moex_carry.news.backfill.fetch_gdelt_news", _mock_gdelt_news)
    monkeypatch.setattr("moex_carry.news.backfill._fetch_price_rows_for_profile", lambda **kwargs: [])

    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        run_news_backfill(
            session,
            settings,
            period_from=date(2025, 1, 1),
            period_to=date(2025, 1, 1),
            commodities=["BRN"],
            include_prices=False,
            run_inference=False,
        )
        links = load_news_entity_links(session, news_ids=["news-unrelated-profile"], limit=50)

    assert all(str(row.get("link_stage") or "") != "source_profile" for row in links)


def test_news_backfill_shock_first_prioritizes_high_move_window(tmp_path, monkeypatch):
    settings = _build_settings(tmp_path)
    settings.news_ingest.gdelt_enabled = False
    settings.news_ingest.newsapi_enabled = True
    settings.news_ingest.newsapi_api_key = "test-key"
    settings.news_ingest.newsapi_daily_limit = 1
    settings.news_ingest.newsapi_daily_state_path = str(tmp_path / "newsapi_usage.json")
    settings.news_ingest.newsapi_backfill_max_pages_per_window = 1
    settings.news_ingest.newsapi_max_records_per_call = 5
    settings.news_ingest.backfill_chunk_days = 1
    settings.news_ingest.backfill_max_windows_per_commodity = 0
    settings.news_ingest.backfill_window_order = "shock_first"
    settings.news_ingest.qc_min_news_per_ticker = 0
    settings.news_ingest.qc_min_price_points_per_ticker = 0

    requested_dates: list[date] = []

    def _mock_newsapi_news(*, query, start_dt, end_dt, **_kwargs):
        requested_dates.append(start_dt.date())
        marker = str(start_dt.date())
        news_id = f"news-shock-order-{abs(hash((query, marker))) % 1000000:06d}"
        return [
            {
                "news_id": news_id,
                "source": "newsapi:test",
                "url": f"https://example.org/{news_id}",
                "title": f"{query} headline",
                "content": "weather-driven demand shock",
                "language": "en",
                "published_at": start_dt.isoformat().replace("+00:00", "Z"),
                "ingested_at": (start_dt + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "hash": f"hash-{news_id}",
            }
        ]

    monkeypatch.setattr("moex_carry.news.backfill.fetch_newsapi_news", _mock_newsapi_news)

    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        upsert_quotes(
            session,
            [
                {"secid": "NG_US", "timestamp": "2026-01-01T00:00:00Z", "last": 100.0},
                {"secid": "NG_US", "timestamp": "2026-01-02T00:00:00Z", "last": 120.0},
                {"secid": "NG_US", "timestamp": "2026-01-03T00:00:00Z", "last": 121.0},
            ],
        )
        report = run_news_backfill(
            session,
            settings,
            period_from=date(2026, 1, 1),
            period_to=date(2026, 1, 3),
            commodities=["NG_US"],
            include_prices=False,
            run_inference=False,
        )

    assert report.window_order == "shock_first"
    assert report.newsapi_requests_used == 1
    assert requested_dates == [date(2026, 1, 2)]


def test_shock_score_uses_hourly_closes_not_single_5m_spike(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        upsert_quotes(
            session,
            [
                {"secid": "NG_US", "timestamp": "2026-01-15T10:00:00Z", "last": 100.0},
                {"secid": "NG_US", "timestamp": "2026-01-15T10:05:00Z", "last": 200.0},
                {"secid": "NG_US", "timestamp": "2026-01-15T10:55:00Z", "last": 100.0},
                {"secid": "NG_US", "timestamp": "2026-01-15T11:55:00Z", "last": 101.0},
            ],
        )
        window_start = datetime.fromisoformat("2026-01-15T10:00:00+00:00")
        window_end = datetime.fromisoformat("2026-01-15T12:00:00+00:00")
        score_map = _shock_score_by_window(
            session,
            ticker="NG_US",
            windows=[(window_start, window_end)],
            shock_bar_minutes=60,
        )

    value = float(score_map.get((window_start, window_end), 0.0))
    # Hourly close-to-close move should be ~ln(101/100), not ln(200/100).
    assert value < 0.05


def test_upsert_news_items_merges_duplicate_url_across_sources(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        upsert_news_items(
            session,
            [
                {
                    "news_id": "news-a",
                    "source": "gdelt",
                    "url": "https://example.org/shared",
                    "title": "Original source",
                    "content": "short",
                    "language": "en",
                    "published_at": "2026-01-21T10:00:00Z",
                    "ingested_at": "2026-01-21T10:01:00Z",
                    "hash": "hash-a",
                }
            ],
        )
        upsert_news_items(
            session,
            [
                {
                    "news_id": "news-b",
                    "source": "newsapi:Reuters",
                    "url": "https://example.org/shared",
                    "title": "Republished source",
                    "content": "longer content payload",
                    "language": "en",
                    "published_at": "2026-01-21T10:00:00Z",
                    "ingested_at": "2026-01-21T10:02:00Z",
                    "hash": "hash-b",
                }
            ],
        )
        rows = load_news_items(session, limit=10)

    shared = [row for row in rows if row.get("url") == "https://example.org/shared"]
    assert len(shared) == 1
    assert shared[0]["news_id"] == "news-a"
    assert shared[0]["content"] == "longer content payload"
