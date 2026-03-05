from __future__ import annotations

import sqlite3


def init_news_live_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_articles (
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
            story_id TEXT,
            raw_json TEXT
        )
        """
    )
    article_columns = {
        str(row[1]).strip().lower()
        for row in conn.execute("PRAGMA table_info(news_articles)").fetchall()
    }
    if "story_id" not in article_columns:
        conn.execute("ALTER TABLE news_articles ADD COLUMN story_id TEXT")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_news_articles_commodity_ts
        ON news_articles (commodity, published_at_utc DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_news_articles_published_ts
        ON news_articles (published_at_utc DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_news_articles_story_id
        ON news_articles (story_id, published_at_utc DESC)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_scores (
            article_id TEXT PRIMARY KEY,
            model_name TEXT NOT NULL,
            scored_at_utc TEXT NOT NULL,
            direction TEXT NOT NULL,
            impact_score REAL NOT NULL,
            confidence REAL NOT NULL,
            severity TEXT NOT NULL,
            reason_terms_up TEXT,
            reason_terms_down TEXT,
            cause_classification TEXT NOT NULL DEFAULT 'unknown',
            cause_bucket TEXT,
            cause_event TEXT,
            transmission_channel TEXT,
            cause_cluster_key TEXT,
            cause_confidence REAL NOT NULL DEFAULT 0.0,
            fundamental_score REAL NOT NULL DEFAULT 0.0,
            direction_alignment REAL NOT NULL DEFAULT 0.5,
            is_primary_cause INTEGER NOT NULL DEFAULT 0,
            cause_route_key TEXT,
            cause_claim_status TEXT NOT NULL DEFAULT 'unknown',
            cause_entities_json TEXT,
            cause_terms_json TEXT,
            effect_terms_json TEXT,
            FOREIGN KEY (article_id) REFERENCES news_articles(article_id)
        )
        """
    )
    score_columns = {
        str(row[1]).strip().lower()
        for row in conn.execute("PRAGMA table_info(news_scores)").fetchall()
    }
    if "cause_classification" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN cause_classification TEXT NOT NULL DEFAULT 'unknown'")
    if "cause_bucket" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN cause_bucket TEXT")
    if "cause_event" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN cause_event TEXT")
    if "transmission_channel" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN transmission_channel TEXT")
    if "cause_cluster_key" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN cause_cluster_key TEXT")
    if "cause_confidence" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN cause_confidence REAL NOT NULL DEFAULT 0.0")
    if "fundamental_score" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN fundamental_score REAL NOT NULL DEFAULT 0.0")
    if "direction_alignment" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN direction_alignment REAL NOT NULL DEFAULT 0.5")
    if "is_primary_cause" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN is_primary_cause INTEGER NOT NULL DEFAULT 0")
    if "cause_route_key" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN cause_route_key TEXT")
    if "cause_claim_status" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN cause_claim_status TEXT NOT NULL DEFAULT 'unknown'")
    if "cause_entities_json" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN cause_entities_json TEXT")
    if "cause_terms_json" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN cause_terms_json TEXT")
    if "effect_terms_json" not in score_columns:
        conn.execute("ALTER TABLE news_scores ADD COLUMN effect_terms_json TEXT")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_news_scores_confidence_impact
        ON news_scores (confidence DESC, impact_score DESC, article_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_news_scores_impact_confidence
        ON news_scores (impact_score DESC, confidence DESC, article_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_news_scores_cause_priority
        ON news_scores (is_primary_cause DESC, fundamental_score DESC, impact_score DESC, confidence DESC, article_id)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_state (
            state_key TEXT PRIMARY KEY,
            state_value TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS newsapi_usage (
            day_utc TEXT PRIMARY KEY,
            used_live INTEGER NOT NULL DEFAULT 0,
            used_backfill INTEGER NOT NULL DEFAULT 0,
            updated_at_utc TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_fetch_runs (
            run_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            started_at_utc TEXT NOT NULL,
            finished_at_utc TEXT NOT NULL,
            fetched_total INTEGER NOT NULL,
            inserted_total INTEGER NOT NULL,
            scored_total INTEGER NOT NULL,
            provider_counts_json TEXT NOT NULL,
            commodity_counts_json TEXT NOT NULL
        )
        """
    )
    conn.commit()
