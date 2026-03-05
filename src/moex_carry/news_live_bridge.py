from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from moex_carry.config import AppSettings
from moex_carry.domain.decision import NewsItem
from moex_carry.news_live_runtime import _parse_any_utc, _sqlite_path_from_url


def load_news_gate_items(
    settings: AppSettings,
    *,
    as_of_utc: datetime | None = None,
) -> list[NewsItem]:
    if not settings.news_filter.live_ingest_enabled:
        return []
    db_path = _sqlite_path_from_url(settings.news_filter.live_db_url)
    if not db_path.exists():
        return []
    now_utc = as_of_utc or datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(minutes=max(settings.news_filter.lookback_minutes, 1))
    cutoff_iso = cutoff.isoformat().replace("+00:00", "Z")

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                a.article_id,
                a.published_at_utc,
                a.source_name,
                a.title,
                s.severity,
                s.impact_score,
                s.confidence,
                a.provider,
                a.commodity
            FROM news_articles a
            JOIN news_scores s ON a.article_id = s.article_id
            WHERE a.published_at_utc >= ?
              AND s.impact_score >= ?
              AND s.confidence >= ?
            ORDER BY a.published_at_utc DESC
            LIMIT ?
            """,
            (
                cutoff_iso,
                float(settings.news_filter.live_min_impact_score),
                float(settings.news_filter.live_min_confidence),
                int(settings.news_filter.live_max_items),
            ),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()

    allowed_sources = {item.strip().lower() for item in settings.news_filter.sources if item.strip()}
    items: list[NewsItem] = []
    for row in rows:
        article_id, published_at_utc, source_name, title, severity, impact_score, _confidence, provider, commodity = row
        source = str(source_name or provider or "news").strip()
        if allowed_sources and source.lower() not in allowed_sources:
            continue
        ts = _parse_any_utc(published_at_utc)
        if ts is None:
            continue
        items.append(
            NewsItem(
                item_id=str(article_id),
                timestamp=ts,
                source=source,
                title=str(title or f"{commodity} news").strip() or f"{commodity} news",
                severity=str(severity or "low").strip().lower(),
                impact_score=float(impact_score or 0.0),
            )
        )
    return items
