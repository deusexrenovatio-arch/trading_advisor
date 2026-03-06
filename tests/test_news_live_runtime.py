from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from moex_carry.config import AppSettings
from moex_carry.news_live_bridge import load_news_gate_items
from moex_carry.news_live_runtime import CommodityProfile, NewsIngestConfig, run_news_ingest_cycle


def _sqlite_path(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_run_news_ingest_cycle_persists_and_scores(monkeypatch, tmp_path):
    db_path = tmp_path / "news_live.db"
    discovery_feed_path = tmp_path / "data" / "output" / "news_live" / "live_news_discovery.csv"
    verified_feed_path = tmp_path / "data" / "output" / "news_live" / "live_news_verified.csv"

    def _fake_gdelt(*args, **kwargs):
        return [
            {
                "provider": "gdelt",
                "published_at_utc": "2026-03-02T10:00:00Z",
                "source_name": "unit-test",
                "title": "Cold storm hits U.S. gas fields",
                "description": "Freeze-off risks and withdrawal expectations grow.",
                "content": "",
                "url": "https://example.test/ng-cold-storm",
                "language": "en",
                "raw": {"id": 1},
            }
        ]

    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_gdelt_articles", _fake_gdelt)
    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_newsapi_articles", lambda *args, **kwargs: [])

    cfg = NewsIngestConfig(
        database_url=_sqlite_path(db_path),
        commodity_profiles=(
            CommodityProfile(
                ticker="NG_US",
                name="US Natural Gas",
                gdelt_query="natural gas",
                newsapi_query="natural gas",
            ),
        ),
        newsapi_enabled=False,
        discovery_feed_path=str(discovery_feed_path),
        verified_feed_path=str(verified_feed_path),
        model_mode="keyword",
    )
    result = run_news_ingest_cycle(config=cfg, mode="live", now_utc=datetime(2026, 3, 3, tzinfo=timezone.utc))

    assert result["inserted_total"] == 1
    assert result["scored_total"] == 1
    assert result["feed_path"] == str(discovery_feed_path)
    assert result["discovery_feed_path"] == str(discovery_feed_path)
    assert result["verified_feed_path"] == str(verified_feed_path)
    assert discovery_feed_path.exists()
    assert verified_feed_path.exists()

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT commodity, title FROM news_articles").fetchone()
        assert row is not None
        assert row[0] == "NG_US"
        assert "storm" in row[1].lower()
        score = conn.execute("SELECT direction, impact_score FROM news_scores").fetchone()
        assert score is not None
        assert score[0] in {"up", "down", "hold"}
        assert float(score[1]) >= 0.0
    finally:
        conn.close()


def test_run_news_ingest_cycle_expands_queries_with_event_first_terms(monkeypatch, tmp_path):
    db_path = tmp_path / "news_live_query_expand.db"
    seen_queries: list[str] = []

    def _fake_gdelt(*args, **kwargs):
        seen_queries.append(str(kwargs.get("query") or ""))
        return []

    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_gdelt_articles", _fake_gdelt)
    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_newsapi_articles", lambda *args, **kwargs: [])

    cfg = NewsIngestConfig(
        database_url=_sqlite_path(db_path),
        commodity_profiles=(
            CommodityProfile(
                ticker="BRN",
                name="Brent",
                gdelt_query="brent crude",
                newsapi_query="brent crude",
            ),
        ),
        newsapi_enabled=False,
        model_mode="keyword",
    )
    run_news_ingest_cycle(config=cfg, mode="live", now_utc=datetime(2026, 3, 3, tzinfo=timezone.utc))

    assert seen_queries
    query = seen_queries[0].lower()
    assert "brent crude" in query
    assert "strait of hormuz" in query
    assert "shipping halted" in query


def test_run_news_ingest_cycle_backfills_causal_fields_for_legacy_scores(tmp_path):
    db_path = tmp_path / "news_live_legacy_scores.db"
    feed_path = tmp_path / "feed_legacy.csv"

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE news_articles (
                article_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                commodity TEXT NOT NULL,
                source_name TEXT,
                published_at_utc TEXT NOT NULL,
                fetched_at_utc TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                content TEXT,
                url TEXT,
                language TEXT,
                query_text TEXT,
                raw_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE news_scores (
                article_id TEXT PRIMARY KEY,
                model_name TEXT NOT NULL,
                scored_at_utc TEXT NOT NULL,
                direction TEXT NOT NULL,
                impact_score REAL NOT NULL,
                confidence REAL NOT NULL,
                severity TEXT NOT NULL,
                reason_terms_up TEXT,
                reason_terms_down TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO news_articles (
                article_id, provider, commodity, source_name, published_at_utc, fetched_at_utc,
                title, description, content, url, language, query_text, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-1",
                "gdelt",
                "BRN",
                "legacy-feed",
                "2026-03-03T10:00:00Z",
                "2026-03-03T10:01:00Z",
                "Pipeline attack disrupts crude exports",
                "Export route outage increases supply risk.",
                "",
                "https://example.test/legacy-1",
                "en",
                "brent",
                "{}",
            ),
        )
        conn.execute(
            """
            INSERT INTO news_scores (
                article_id, model_name, scored_at_utc, direction, impact_score, confidence, severity, reason_terms_up, reason_terms_down
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-1",
                "legacy-model",
                "2026-03-03T10:02:00Z",
                "up",
                0.8,
                0.85,
                "high",
                '["supply risk","exports"]',
                "[]",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    cfg = NewsIngestConfig(
        database_url=_sqlite_path(db_path),
        commodity_profiles=(
            CommodityProfile(
                ticker="BRN",
                name="Brent",
                gdelt_query="brent",
                newsapi_query="brent",
            ),
        ),
        gdelt_enabled=False,
        newsapi_enabled=False,
        feed_path=str(feed_path),
        model_mode="keyword",
    )
    result = run_news_ingest_cycle(config=cfg, mode="live", now_utc=datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc))

    assert result["inserted_total"] == 0
    assert result["scored_total"] == 0
    assert result["causal_backfilled_total"] == 1

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT cause_classification, cause_bucket, fundamental_score, is_primary_cause
            FROM news_scores
            WHERE article_id = 'legacy-1'
            """
        ).fetchone()
        assert row is not None
        assert str(row[0]).strip().lower() in {"unknown", "effect", "mixed", "cause"}
        assert float(row[2]) >= 0.0
        assert int(row[3]) in {0, 1}
    finally:
        conn.close()


def test_newsapi_budget_blocks_second_request(monkeypatch, tmp_path):
    db_path = tmp_path / "news_live_budget.db"
    calls = {"newsapi": 0}

    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_gdelt_articles", lambda *args, **kwargs: [])

    def _fake_newsapi(*args, **kwargs):
        calls["newsapi"] += 1
        return []

    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_newsapi_articles", _fake_newsapi)

    cfg = NewsIngestConfig(
        database_url=_sqlite_path(db_path),
        commodity_profiles=(
            CommodityProfile(
                ticker="BRN",
                name="Brent",
                gdelt_query="brent",
                newsapi_query="brent",
            ),
        ),
        gdelt_enabled=False,
        newsapi_enabled=True,
        newsapi_api_key="test-key",
        newsapi_daily_quota=1,
        newsapi_realtime_budget=1,
        newsapi_backfill_budget=0,
        newsapi_emergency_buffer=0,
        model_mode="keyword",
    )
    run_news_ingest_cycle(config=cfg, mode="live", now_utc=datetime(2026, 3, 3, 8, 0, tzinfo=timezone.utc))
    run_news_ingest_cycle(config=cfg, mode="live", now_utc=datetime(2026, 3, 3, 8, 5, tzinfo=timezone.utc))
    assert calls["newsapi"] == 1


def test_newsapi_live_min_interval_throttles_calls(monkeypatch, tmp_path):
    db_path = tmp_path / "news_live_interval.db"
    calls = {"newsapi": 0}

    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_gdelt_articles", lambda *args, **kwargs: [])

    def _fake_newsapi(*args, **kwargs):
        calls["newsapi"] += 1
        return []

    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_newsapi_articles", _fake_newsapi)

    cfg = NewsIngestConfig(
        database_url=_sqlite_path(db_path),
        commodity_profiles=(
            CommodityProfile(
                ticker="BRN",
                name="Brent",
                gdelt_query="brent",
                newsapi_query="brent",
            ),
        ),
        gdelt_enabled=False,
        newsapi_enabled=True,
        newsapi_api_key="test-key",
        newsapi_live_min_interval_minutes=90,
        model_mode="keyword",
    )
    run_news_ingest_cycle(config=cfg, mode="live", now_utc=datetime(2026, 3, 3, 8, 0, tzinfo=timezone.utc))
    run_news_ingest_cycle(config=cfg, mode="live", now_utc=datetime(2026, 3, 3, 8, 30, tzinfo=timezone.utc))
    run_news_ingest_cycle(config=cfg, mode="live", now_utc=datetime(2026, 3, 3, 9, 31, tzinfo=timezone.utc))
    assert calls["newsapi"] == 2


def test_gdelt_retry_recovers_transient_failure(monkeypatch, tmp_path):
    db_path = tmp_path / "news_live_retry.db"
    feed_path = tmp_path / "feed_retry.csv"
    calls = {"gdelt": 0}

    def _flaky_gdelt(*args, **kwargs):
        calls["gdelt"] += 1
        if calls["gdelt"] == 1:
            raise RuntimeError("transient gdelt issue")
        return [
            {
                "provider": "gdelt",
                "published_at_utc": "2026-03-02T10:00:00Z",
                "source_name": "unit-test",
                "title": "Refinery outage tightens market",
                "description": "Supply disruption raises near-term price risk.",
                "content": "",
                "url": "https://example.test/brn-outage",
                "language": "en",
                "raw": {"id": 99},
            }
        ]

    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_gdelt_articles", _flaky_gdelt)
    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_newsapi_articles", lambda *args, **kwargs: [])

    cfg = NewsIngestConfig(
        database_url=_sqlite_path(db_path),
        commodity_profiles=(
            CommodityProfile(
                ticker="BRN",
                name="Brent",
                gdelt_query="brent",
                newsapi_query="brent",
            ),
        ),
        newsapi_enabled=False,
        feed_path=str(feed_path),
        model_mode="keyword",
        gdelt_retry_attempts=2,
        gdelt_retry_backoff_sec=0.0,
    )
    result = run_news_ingest_cycle(config=cfg, mode="live", now_utc=datetime(2026, 3, 3, 10, 0, tzinfo=timezone.utc))
    assert calls["gdelt"] == 2
    assert result["inserted_total"] == 1


def test_load_news_gate_items_reads_scored_rows(monkeypatch, tmp_path):
    db_path = tmp_path / "news_live_bridge.db"
    feed_path = tmp_path / "data" / "output" / "news_live" / "live_news_discovery.csv"
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    now_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    published_at = (now_utc - timedelta(minutes=20)).isoformat().replace("+00:00", "Z")

    def _fake_gdelt(*args, **kwargs):
        return [
            {
                "provider": "gdelt",
                "published_at_utc": published_at,
                "source_name": "trusted-feed",
                "title": "Official statement confirms Strait of Hormuz closure after missile attack",
                "description": "Shipping halted as tanker transit is suspended.",
                "content": "",
                "url": "https://example.test/brent-shock",
                "language": "en",
                "raw": {"id": 2},
            }
        ]

    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_gdelt_articles", _fake_gdelt)
    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_newsapi_articles", lambda *args, **kwargs: [])

    cfg = NewsIngestConfig(
        database_url=_sqlite_path(db_path),
        commodity_profiles=(
            CommodityProfile(
                ticker="BRN",
                name="Brent",
                gdelt_query="brent",
                newsapi_query="brent",
            ),
        ),
        newsapi_enabled=False,
        feed_path=str(feed_path),
        model_mode="keyword",
    )
    run_news_ingest_cycle(config=cfg, mode="live", now_utc=now_utc)
    feed_df = pd.read_csv(feed_path)
    feed_df["confidence"] = 0.5
    feed_df.to_csv(feed_path, index=False)

    settings = AppSettings()
    settings.data.data_dir = str(tmp_path / "data")
    settings.news_filter.live_ingest_enabled = True
    settings.news_filter.live_db_url = _sqlite_path(db_path)
    settings.news_filter.live_feed_path = str(feed_path)
    settings.news_filter.live_min_impact_score = 0.0
    settings.news_filter.live_min_confidence = 0.9
    settings.news_filter.live_max_items = 20
    settings.news_filter.lookback_minutes = 24 * 60
    settings.news_filter.sources = ["trusted-feed"]

    items = load_news_gate_items(settings, as_of_utc=now_utc)
    assert not items

    settings.news_filter.live_min_confidence = 0.4
    items = load_news_gate_items(settings, as_of_utc=now_utc)
    assert items
    assert items[0].source == "trusted-feed"


def test_scoring_deduplicates_cross_commodity_story(monkeypatch, tmp_path):
    db_path = tmp_path / "news_live_story_dedup.db"
    feed_path = tmp_path / "feed_story_dedup.csv"
    calls = {"score": 0}

    def _fake_gdelt(*args, **kwargs):
        return [
            {
                "provider": "gdelt",
                "published_at_utc": "2026-03-02T10:00:00Z",
                "source_name": "unit-test",
                "title": "Iran conflict lifts oil and gas risk premium",
                "description": "Market reacts to supply-route risk.",
                "content": "",
                "url": "https://example.test/shared-story",
                "language": "en",
                "raw": {"id": 101},
            }
        ]

    def _fake_score(self, *, commodity, title, description, content):
        calls["score"] += 1
        return {
            "model_name": "unit-score",
            "direction": "up",
            "impact_score": 0.9,
            "confidence": 0.95,
            "severity": "critical",
            "reason_terms_up": ["risk"],
            "reason_terms_down": [],
        }

    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_gdelt_articles", _fake_gdelt)
    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_newsapi_articles", lambda *args, **kwargs: [])
    monkeypatch.setattr("moex_carry.news_live_runtime.ModelScorer.score", _fake_score)

    cfg = NewsIngestConfig(
        database_url=_sqlite_path(db_path),
        commodity_profiles=(
            CommodityProfile(
                ticker="BRN",
                name="Brent",
                gdelt_query="brent",
                newsapi_query="brent",
            ),
            CommodityProfile(
                ticker="NG_US",
                name="Natural Gas",
                gdelt_query="natural gas",
                newsapi_query="natural gas",
            ),
        ),
        newsapi_enabled=False,
        feed_path=str(feed_path),
        model_mode="keyword",
    )
    result = run_news_ingest_cycle(config=cfg, mode="live", now_utc=datetime(2026, 3, 3, tzinfo=timezone.utc))
    assert result["inserted_total"] == 1
    assert result["scored_total"] == 1
    assert calls["score"] == 1

    conn = sqlite3.connect(db_path)
    try:
        story_stats = conn.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT story_id)
            FROM news_articles
            """
        ).fetchone()
        assert story_stats is not None
        assert int(story_stats[0]) == 1
        assert int(story_stats[1]) == 1
        link_stats = conn.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT commodity)
            FROM news_article_commodity_links
            """
        ).fetchone()
        assert link_stats is not None
        assert int(link_stats[0]) == 2
        assert int(link_stats[1]) == 2
    finally:
        conn.close()


def test_backfill_cursor_advances_only_after_success(monkeypatch, tmp_path):
    db_path = tmp_path / "news_live_backfill_cursor.db"
    now_utc = datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_newsapi_articles", lambda *args, **kwargs: [])
    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_gdelt_articles", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("gdelt down")))

    cfg = NewsIngestConfig(
        database_url=_sqlite_path(db_path),
        commodity_profiles=(
            CommodityProfile(
                ticker="BRN",
                name="Brent",
                gdelt_query="brent",
                newsapi_query="brent",
            ),
        ),
        gdelt_enabled=True,
        newsapi_enabled=False,
        backfill_chunk_days=30,
        backfill_max_windows_per_commodity=2,
        model_mode="keyword",
    )
    run_news_ingest_cycle(config=cfg, mode="backfill", now_utc=now_utc)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT state_value FROM news_state WHERE state_key = ?",
            ("backfill_cursor_utc:gdelt:BRN",),
        ).fetchone()
        assert row is None
    finally:
        conn.close()

    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_gdelt_articles", lambda *args, **kwargs: [])
    run_news_ingest_cycle(config=cfg, mode="backfill", now_utc=now_utc)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT state_value FROM news_state WHERE state_key = ?",
            ("backfill_cursor_utc:gdelt:BRN",),
        ).fetchone()
        assert row is not None
        value = str(row[0])
        assert value.startswith("2026-01-03T12:00:00")
    finally:
        conn.close()


def test_newsapi_backfill_uses_multiple_windows_and_updates_cursor(monkeypatch, tmp_path):
    db_path = tmp_path / "news_live_newsapi_backfill.db"
    now_utc = datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)
    calls: list[tuple[datetime, datetime]] = []

    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_gdelt_articles", lambda *args, **kwargs: [])

    def _fake_newsapi(*args, **kwargs):
        start_utc = kwargs["start_utc"]
        end_utc = kwargs["end_utc"]
        calls.append((start_utc, end_utc))
        return [
            {
                "provider": "newsapi",
                "published_at_utc": end_utc.isoformat().replace("+00:00", "Z"),
                "source_name": "unit-test",
                "title": f"Backfill window ending {end_utc.date()}",
                "description": "Windowed backfill test.",
                "content": "",
                "url": f"https://example.test/newsapi/{end_utc.strftime('%Y%m%d%H%M')}",
                "language": "en",
                "raw": {"window_end": end_utc.isoformat()},
            }
        ]

    monkeypatch.setattr("moex_carry.news_live_runtime._fetch_newsapi_articles", _fake_newsapi)

    cfg = NewsIngestConfig(
        database_url=_sqlite_path(db_path),
        commodity_profiles=(
            CommodityProfile(
                ticker="BRN",
                name="Brent",
                gdelt_query="brent",
                newsapi_query="brent",
            ),
        ),
        gdelt_enabled=False,
        newsapi_enabled=True,
        newsapi_api_key="test-key",
        backfill_chunk_days=1,
        newsapi_backfill_windows_per_commodity=2,
        newsapi_daily_quota=10,
        newsapi_backfill_budget=10,
        newsapi_realtime_budget=0,
        newsapi_emergency_buffer=0,
        model_mode="keyword",
    )
    result = run_news_ingest_cycle(config=cfg, mode="backfill", now_utc=now_utc)
    assert result["inserted_total"] == 2
    assert len(calls) == 2
    assert calls[0][0] == datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc)
    assert calls[0][1] == datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)
    assert calls[1][0] == datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)
    assert calls[1][1] == datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc)

    conn = sqlite3.connect(db_path)
    try:
        cursor_row = conn.execute(
            "SELECT state_value FROM news_state WHERE state_key = ?",
            ("backfill_cursor_utc:newsapi:BRN",),
        ).fetchone()
        assert cursor_row is not None
        assert str(cursor_row[0]).startswith("2026-03-02T12:00:00")
    finally:
        conn.close()
