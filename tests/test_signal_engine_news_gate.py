from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from moex_carry.signal_engine.news.gate import CommodityNewsGate


def _init_news_db(path: Path) -> None:
    conn = sqlite3.connect(path)
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
                title TEXT NOT NULL
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
                severity TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert_news(
    *,
    path: Path,
    article_id: str,
    commodity: str,
    ts: datetime,
    severity: str,
    impact_score: float = 0.8,
    confidence: float = 0.95,
) -> None:
    published = ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO news_articles (
                article_id, provider, commodity, source_name, published_at_utc, fetched_at_utc, title
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id,
                "test",
                commodity,
                "UnitTestFeed",
                published,
                published,
                f"{commodity} headline",
            ),
        )
        conn.execute(
            """
            INSERT INTO news_scores (
                article_id, model_name, scored_at_utc, direction, impact_score, confidence, severity
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id,
                "keyword_v1",
                published,
                "neutral",
                float(impact_score),
                float(confidence),
                severity,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_news_gate_uses_causal_cutoff_and_ignores_future_rows(tmp_path):
    db_path = tmp_path / "news.db"
    _init_news_db(db_path)
    as_of = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    _insert_news(
        path=db_path,
        article_id="medium_now",
        commodity="BRN",
        ts=as_of - timedelta(minutes=30),
        severity="medium",
    )
    _insert_news(
        path=db_path,
        article_id="high_future",
        commodity="BRN",
        ts=as_of + timedelta(minutes=10),
        severity="high",
    )
    gate = CommodityNewsGate(
        {
            "enabled": True,
            "db_url": f"sqlite:///{db_path}",
            "lookback_minutes": 180,
            "block_severity_threshold": "high",
            "reduce_severity_threshold": "medium",
            "commodity_map": {"BR": "BRN"},
        }
    )

    decision = gate.evaluate(as_of_ts=as_of, instrument_id="BRH6")

    assert decision.action == "reduce"
    assert len(decision.matched_items) == 1
    assert decision.matched_items[0].article_id == "medium_now"


def test_news_gate_blocks_on_high_severity(tmp_path):
    db_path = tmp_path / "news.db"
    _init_news_db(db_path)
    as_of = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    _insert_news(
        path=db_path,
        article_id="high_now",
        commodity="NG_US",
        ts=as_of - timedelta(minutes=15),
        severity="high",
    )
    gate = CommodityNewsGate(
        {
            "enabled": True,
            "db_url": f"sqlite:///{db_path}",
            "lookback_minutes": 180,
            "block_severity_threshold": "high",
            "reduce_severity_threshold": "medium",
            "commodity_map": {"NG": "NG_US"},
        }
    )

    decision = gate.evaluate(as_of_ts=as_of, instrument_id="NGH6")

    assert decision.action == "block"
    assert decision.highest_severity == "high"
    assert len(decision.matched_items) == 1


def test_news_gate_allows_unmapped_instrument(tmp_path):
    db_path = tmp_path / "news.db"
    _init_news_db(db_path)
    gate = CommodityNewsGate(
        {
            "enabled": True,
            "db_url": f"sqlite:///{db_path}",
            "commodity_map": {"BR": "BRN"},
        }
    )
    as_of = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)

    decision = gate.evaluate(as_of_ts=as_of, instrument_id="SILVERH6")

    assert decision.action == "allow"
    assert "commodity_unmapped" in decision.reasons
