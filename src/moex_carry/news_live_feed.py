from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from moex_carry.news_storage import write_csv_atomic
from moex_carry.news_topic import build_story_fingerprint


def build_live_news_feed_frame(
    conn: sqlite3.Connection,
    *,
    min_impact_score: float,
    min_confidence: float,
    max_rows: int,
) -> pd.DataFrame:
    columns = [
        "article_id",
        "story_id",
        "published_at_utc",
        "commodity",
        "commodity_scope",
        "direction",
        "severity",
        "impact_score",
        "confidence",
        "source_name",
        "provider",
        "title",
        "url",
        "story_key",
        "reason_terms_up",
        "reason_terms_down",
    ]
    rows = conn.execute(
        """
        SELECT
            a.article_id,
            a.story_id,
            a.published_at_utc,
            a.commodity,
            '' AS commodity_scope,
            s.direction,
            s.severity,
            s.impact_score,
            s.confidence,
            a.source_name,
            a.provider,
            a.title,
            a.url,
            '' AS story_key,
            s.reason_terms_up,
            s.reason_terms_down
        FROM news_articles a
        JOIN news_scores s ON a.article_id = s.article_id
        WHERE s.impact_score >= ?
          AND s.confidence >= ?
        ORDER BY a.published_at_utc DESC
        LIMIT ?
        """,
        (float(min_impact_score), float(min_confidence), int(max_rows) * 5),
    ).fetchall()
    if not rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows, columns=columns)
    df["story_key"] = (
        df["story_id"].fillna("").astype(str).str.strip().where(
            df["story_id"].fillna("").astype(str).str.strip().ne(""),
            df.apply(
                lambda row: build_story_fingerprint(
                    title=row.get("title"),
                    url=row.get("url"),
                    published_at_utc=row.get("published_at_utc"),
                    provider=row.get("provider"),
                ),
                axis=1,
            ),
        )
    )

    commodity_scope = (
        df.groupby("story_key")["commodity"]
        .apply(
            lambda values: ",".join(
                sorted(dict.fromkeys(str(item).strip().upper() for item in values if str(item).strip()))
            )
        )
        .to_dict()
    )

    ranked = df.assign(
        _score=(pd.to_numeric(df["impact_score"], errors="coerce").fillna(0.0) * 2.0)
        + pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0)
    )
    ranked = ranked.sort_values(["_score", "published_at_utc"], ascending=[False, False])
    ranked = ranked.drop_duplicates(subset=["story_key"], keep="first")
    ranked["commodity_scope"] = ranked["story_key"].map(commodity_scope).fillna(ranked["commodity"])
    ranked = ranked.sort_values("published_at_utc", ascending=False)
    if max_rows > 0:
        ranked = ranked.head(int(max_rows))
    return ranked.drop(columns=["_score", "story_id"]).reset_index(drop=True)


def export_live_news_feed(
    conn: sqlite3.Connection,
    *,
    feed_path: Path,
    min_impact_score: float,
    min_confidence: float,
    max_rows: int,
) -> int:
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    df = build_live_news_feed_frame(
        conn,
        min_impact_score=min_impact_score,
        min_confidence=min_confidence,
        max_rows=max_rows,
    )
    write_csv_atomic(df, feed_path)
    return int(len(df))
