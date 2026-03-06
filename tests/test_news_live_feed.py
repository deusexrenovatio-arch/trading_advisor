from __future__ import annotations

import sqlite3

from moex_carry.news_live_feed import build_live_news_feed_frame


def _seed_base_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE news_articles (
            article_id TEXT PRIMARY KEY,
            story_id TEXT,
            published_at_utc TEXT NOT NULL,
            commodity TEXT NOT NULL,
            source_name TEXT,
            provider TEXT,
            title TEXT,
            url TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE news_scores (
            article_id TEXT PRIMARY KEY,
            direction TEXT NOT NULL,
            severity TEXT NOT NULL,
            impact_score REAL NOT NULL,
            confidence REAL NOT NULL,
            reason_terms_up TEXT,
            reason_terms_down TEXT,
            cause_classification TEXT,
            cause_bucket TEXT,
            cause_event TEXT,
            transmission_channel TEXT,
            cause_cluster_key TEXT,
            cause_confidence REAL,
            fundamental_score REAL,
            direction_alignment REAL,
            is_primary_cause INTEGER,
            cause_terms_json TEXT,
            effect_terms_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE news_shock_rows (
            selected_event_id TEXT,
            v2_event_id TEXT,
            broad_event_id TEXT,
            shock_ts TEXT,
            shock_direction TEXT,
            abs_move_pct REAL,
            z_score REAL
        )
        """
    )
    conn.commit()


def test_feed_keeps_primary_causes_and_adds_verification_columns() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        _seed_base_tables(conn)
        conn.execute(
            """
            INSERT INTO news_articles (article_id, story_id, published_at_utc, commodity, source_name, provider, title, url)
            VALUES
                ('a1', 'story-a1', '2026-03-05T09:00:00Z', 'BRN', 'wire', 'newsapi', 'OPEC output cut tightens supply', 'https://ex/a1'),
                ('a2', 'story-a2', '2026-03-05T09:30:00Z', 'BRN', 'wire', 'newsapi', 'Oil prices rose on momentum trade', 'https://ex/a2')
            """
        )
        conn.execute(
            """
            INSERT INTO news_scores (
                article_id, direction, severity, impact_score, confidence, reason_terms_up, reason_terms_down,
                cause_classification, cause_bucket, cause_event, transmission_channel, cause_cluster_key,
                cause_confidence, fundamental_score, direction_alignment, is_primary_cause, cause_terms_json, effect_terms_json
            )
            VALUES
                ('a1', 'up', 'high', 0.82, 0.95, '["opec","cut"]', '[]', 'cause', 'supply', 'opec_supply_cut', 'physical_supply', 'cause:BRN:opec_supply_cut:x1', 0.88, 0.91, 1.0, 1, '["opec cut"]', '[]'),
                ('a2', 'up', 'high', 0.90, 0.96, '["momentum"]', '[]', 'effect', 'market_commentary', 'price_reaction', 'none', 'cause:BRN:effect:x2', 0.15, 0.10, 1.0, 0, '[]', '["prices rose"]')
            """
        )
        conn.execute(
            """
            INSERT INTO news_shock_rows (selected_event_id, shock_ts, shock_direction, abs_move_pct, z_score)
            VALUES
                ('a1', '2026-03-05T09:25:00Z', 'up', 1.30, 3.2),
                ('a1', '2026-03-05T15:00:00Z', 'up', 2.10, 4.1)
            """
        )
        conn.commit()

        frame = build_live_news_feed_frame(
            conn,
            min_impact_score=0.1,
            min_confidence=0.1,
            min_fundamental_score=0.45,
            max_rows=20,
            require_primary_cause=True,
            require_verified_move=False,
            require_verified_both_horizons=True,
        )

        assert list(frame["article_id"]) == ["a1"]
        row = frame.iloc[0]
        assert bool(row["verified_move_1h"]) is True
        assert bool(row["verified_move_1d"]) is True
        assert float(row["verification_score"]) > 0.0
    finally:
        conn.close()


def test_feed_verification_gate_respects_both_vs_any_horizon() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        _seed_base_tables(conn)
        conn.execute(
            """
            INSERT INTO news_articles (article_id, story_id, published_at_utc, commodity, source_name, provider, title, url)
            VALUES ('b1', 'story-b1', '2026-03-05T09:00:00Z', 'GOLD', 'wire', 'gdelt', 'Rate cut supports gold demand', 'https://ex/b1')
            """
        )
        conn.execute(
            """
            INSERT INTO news_scores (
                article_id, direction, severity, impact_score, confidence, reason_terms_up, reason_terms_down,
                cause_classification, cause_bucket, cause_event, transmission_channel, cause_cluster_key,
                cause_confidence, fundamental_score, direction_alignment, is_primary_cause, cause_terms_json, effect_terms_json
            )
            VALUES ('b1', 'up', 'high', 0.8, 0.9, '["rate cut"]', '[]', 'cause', 'monetary_policy', 'central_bank_dovish_shift', 'rates_fx', 'cause:GOLD:cb:x1', 0.8, 0.85, 1.0, 1, '["rate cut"]', '[]')
            """
        )
        conn.execute(
            """
            INSERT INTO news_shock_rows (selected_event_id, shock_ts, shock_direction, abs_move_pct, z_score)
            VALUES ('b1', '2026-03-05T14:30:00Z', 'up', 0.90, 2.4)
            """
        )
        conn.commit()

        strict = build_live_news_feed_frame(
            conn,
            min_impact_score=0.1,
            min_confidence=0.1,
            max_rows=20,
            require_primary_cause=True,
            require_verified_move=True,
            require_verified_both_horizons=True,
        )
        relaxed = build_live_news_feed_frame(
            conn,
            min_impact_score=0.1,
            min_confidence=0.1,
            max_rows=20,
            require_primary_cause=True,
            require_verified_move=True,
            require_verified_both_horizons=False,
        )

        assert strict.empty
        assert list(relaxed["article_id"]) == ["b1"]
    finally:
        conn.close()


def test_feed_verification_matches_broad_event_id_when_selected_missing() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        _seed_base_tables(conn)
        conn.execute(
            """
            INSERT INTO news_articles (article_id, story_id, published_at_utc, commodity, source_name, provider, title, url)
            VALUES ('c1', 'story-c1', '2026-03-05T09:00:00Z', 'BRN', 'wire', 'gdelt', 'Iran strike hits export terminal', 'https://ex/c1')
            """
        )
        conn.execute(
            """
            INSERT INTO news_scores (
                article_id, direction, severity, impact_score, confidence, reason_terms_up, reason_terms_down,
                cause_classification, cause_bucket, cause_event, transmission_channel, cause_cluster_key,
                cause_confidence, fundamental_score, direction_alignment, is_primary_cause, cause_terms_json, effect_terms_json
            )
            VALUES ('c1', 'up', 'high', 0.86, 0.93, '["strike"]', '[]', 'cause', 'supply', 'producer_outage', 'physical_supply', 'cause:BRN:outage:c1', 0.81, 0.9, 1.0, 1, '["strike"]', '[]')
            """
        )
        conn.execute(
            """
            INSERT INTO news_shock_rows (selected_event_id, v2_event_id, broad_event_id, shock_ts, shock_direction, abs_move_pct, z_score)
            VALUES (NULL, NULL, 'c1', '2026-03-05T09:20:00Z', 'up', 1.4, 3.1)
            """
        )
        conn.commit()

        frame = build_live_news_feed_frame(
            conn,
            min_impact_score=0.1,
            min_confidence=0.1,
            min_fundamental_score=0.45,
            max_rows=20,
            require_primary_cause=True,
            require_verified_move=True,
            require_verified_both_horizons=False,
        )

        assert list(frame["article_id"]) == ["c1"]
        row = frame.iloc[0]
        assert bool(row["verified_move_1h"]) is True
        assert float(row["verification_score"]) > 0.0
    finally:
        conn.close()


def test_feed_emits_per_commodity_rows_with_story_scope_json() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        _seed_base_tables(conn)
        conn.execute(
            """
            CREATE TABLE news_article_commodity_links (
                article_id TEXT NOT NULL,
                commodity TEXT NOT NULL,
                link_score REAL NOT NULL,
                link_reason TEXT,
                link_evidence_json TEXT,
                link_mode TEXT,
                is_primary_link INTEGER,
                first_seen_at_utc TEXT,
                last_seen_at_utc TEXT,
                PRIMARY KEY (article_id, commodity)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO news_articles (article_id, story_id, published_at_utc, commodity, source_name, provider, title, url)
            VALUES ('m1', 'story-m1', '2026-03-05T09:00:00Z', 'BRN', 'wire', 'newsapi', 'Oil and gold rise on Middle East escalation', 'https://ex/m1')
            """
        )
        conn.execute(
            """
            INSERT INTO news_scores (
                article_id, direction, severity, impact_score, confidence, reason_terms_up, reason_terms_down,
                cause_classification, cause_bucket, cause_event, transmission_channel, cause_cluster_key,
                cause_confidence, fundamental_score, direction_alignment, is_primary_cause, cause_terms_json, effect_terms_json
            )
            VALUES ('m1', 'up', 'high', 0.88, 0.94, '["escalation","safe haven"]', '[]', 'cause', 'geopolitics', 'route_risk', 'physical_supply', 'cause:macro:m1', 0.82, 0.9, 1.0, 1, '["escalation"]', '[]')
            """
        )
        conn.execute(
            """
            INSERT INTO news_article_commodity_links (
                article_id, commodity, link_score, link_reason, link_evidence_json, link_mode, is_primary_link, first_seen_at_utc, last_seen_at_utc
            )
            VALUES
                ('m1', 'BRN', 0.93, 'anchor+seed', '["oil","middle east"]', 'deterministic', 1, '2026-03-05T09:00:00Z', '2026-03-05T09:00:00Z'),
                ('m1', 'GOLD', 0.71, 'anchor', '["gold","safe haven"]', 'deterministic', 0, '2026-03-05T09:00:00Z', '2026-03-05T09:00:00Z')
            """
        )
        conn.commit()

        frame = build_live_news_feed_frame(
            conn,
            feed_role="discovery",
            min_impact_score=0.1,
            min_confidence=0.1,
            min_link_score=0.6,
            max_rows=20,
            require_primary_cause=False,
            require_verified_move=False,
            require_verified_both_horizons=False,
        )

        assert list(frame["commodity"]) == ["BRN", "GOLD"]
        assert set(frame["feed_role"]) == {"discovery"}
        assert set(frame["story_id"]) == {"story-m1"}
        assert all(str(value).startswith("{") for value in frame["story_scope_json"].tolist())
        assert set(frame["commodity_scope"]) == {"BRN,GOLD"}
    finally:
        conn.close()
