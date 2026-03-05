from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from moex_carry.config import AppSettings
from moex_carry.domain.decision import NewsItem
from moex_carry.news_storage import (
    open_sqlite_connection,
    parse_any_utc,
    sqlite_path_from_url,
)


logger = logging.getLogger(__name__)


def load_news_gate_items(settings: AppSettings, *, as_of_utc: datetime | None = None) -> list[NewsItem]:
    if not settings.news_filter.live_ingest_enabled:
        return []
    db_path = sqlite_path_from_url(settings.news_filter.live_db_url, data_dir=settings.data.data_dir)
    if not db_path.exists():
        return []
    now_utc = as_of_utc if as_of_utc is not None else datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)
    cutoff = now_utc - timedelta(minutes=max(settings.news_filter.lookback_minutes, 1))
    cutoff_iso = cutoff.isoformat().replace("+00:00", "Z")

    rows: list[tuple[object, ...]] = []
    attempts = 2
    for attempt in range(1, attempts + 1):
        conn: sqlite3.Connection | None = None
        try:
            conn = open_sqlite_connection(db_path, timeout_sec=5.0, write=False)
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
            break
        except sqlite3.OperationalError as exc:
            if attempt >= attempts:
                logger.warning(
                    "news_live_bridge sqlite operational error after retries: %s (db=%s)",
                    exc,
                    db_path,
                )
                return []
            time.sleep(0.1 * attempt)
        except sqlite3.Error as exc:
            logger.warning("news_live_bridge sqlite error: %s (db=%s)", exc, db_path)
            return []
        finally:
            if conn is not None:
                conn.close()

    allowed_sources = {item.strip().lower() for item in settings.news_filter.sources if item.strip()}
    items: list[NewsItem] = []
    for row in rows:
        article_id, published_at_utc, source_name, title, severity, impact_score, _confidence, provider, commodity = row
        source = str(source_name or provider or "news").strip()
        if allowed_sources and source.lower() not in allowed_sources:
            continue
        ts = parse_any_utc(published_at_utc)
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
