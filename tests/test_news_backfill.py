from __future__ import annotations

from datetime import date, datetime, timedelta

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig, UiConfig
from moex_carry.news.backfill import _fetch_yfinance_series, run_news_backfill, run_news_qc
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db


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
