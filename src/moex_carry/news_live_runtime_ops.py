from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any

from moex_carry.news.linking import score_commodity_links
from moex_carry.news_causal import analyze_causal_news
from moex_carry.news_live_causal_ops import backfill_missing_causal_scores
from moex_carry.news_live_schema import init_news_live_db
from moex_carry.news_live_scoring import MODEL_NAME_KEYWORD, SEVERITY_ORDER, ModelScorer
from moex_carry.news_runtime_state import iso_utc, utc_now
from moex_carry.news_topic import build_story_fingerprint


def normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_url(value: object) -> str:
    url = normalize_text(value)
    if not url:
        return ""
    lowered = url.lower()
    for marker in ("?utm_", "&utm_", "?fbclid=", "&fbclid="):
        idx = lowered.find(marker)
        if idx >= 0:
            return url[:idx]
    return url


def article_id(*, provider: str, title: str, url: str, published_at: str) -> str:
    payload = "|".join(
        [
            provider.strip().lower(),
            normalize_url(url).lower(),
            normalize_text(title).lower(),
            normalize_text(published_at),
        ]
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]
    return f"{provider.lower()}-{digest}"


def story_id(*, provider: str, title: str, url: str, published_at: str) -> str:
    return build_story_fingerprint(
        title=title,
        url=url,
        published_at_utc=published_at,
        provider=provider,
    )


def safe_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


def init_db(conn: sqlite3.Connection) -> None:
    init_news_live_db(conn)


def backfill_story_ids(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT article_id, provider, title, url, published_at_utc
        FROM news_articles
        WHERE COALESCE(story_id, '') = ''
        """
    ).fetchall()
    if not rows:
        return
    for current_article_id, provider, title, url, published_at_utc in rows:
        current_story_id = story_id(
            provider=normalize_text(provider),
            title=normalize_text(title),
            url=normalize_url(url),
            published_at=normalize_text(published_at_utc),
        )
        conn.execute(
            "UPDATE news_articles SET story_id = ? WHERE article_id = ?",
            (current_story_id, str(current_article_id)),
        )
    conn.commit()


def retry_fetch(
    fetch_fn,
    *,
    attempts: int,
    backoff_sec: float,
) -> list[dict[str, Any]]:
    last_exc: Exception | None = None
    total = max(int(attempts), 1)
    for idx in range(total):
        try:
            return fetch_fn()
        except Exception as exc:  # pragma: no cover - retry behavior is covered via call counting tests
            last_exc = exc
            if idx < total - 1 and backoff_sec > 0:
                time.sleep(backoff_sec * float(idx + 1))
    if last_exc is not None:
        raise last_exc
    return []


def insert_articles(
    conn: sqlite3.Connection,
    *,
    commodity: str,
    query_text: str,
    fetched_at_utc: str,
    items: list[dict[str, Any]],
    allowed_commodities: tuple[str, ...],
) -> tuple[int, int]:
    fetched = 0
    inserted = 0
    for item in items:
        title = normalize_text(item.get("title"))
        url = normalize_url(item.get("url"))
        published_at_utc = normalize_text(item.get("published_at_utc"))
        if not title and not url:
            continue
        current_article_id = article_id(
            provider=str(item.get("provider") or "unknown"),
            title=title,
            url=url,
            published_at=published_at_utc,
        )
        current_story_id = story_id(
            provider=str(item.get("provider") or "unknown"),
            title=title,
            url=url,
            published_at=published_at_utc,
        )
        fetched += 1
        exists = conn.execute(
            "SELECT 1 FROM news_articles WHERE article_id = ?",
            (current_article_id,),
        ).fetchone()
        if exists is not None:
            conn.execute(
                """
                UPDATE news_articles
                SET fetched_at_utc = ?, raw_json = ?, story_id = ?, query_text = ?
                WHERE article_id = ?
                """,
                (
                    fetched_at_utc,
                    safe_json(item.get("raw")),
                    current_story_id,
                    query_text,
                    current_article_id,
                ),
            )
            upsert_article_links(
                conn,
                article_id=current_article_id,
                seed_commodity=commodity,
                title=title or "(untitled)",
                description=normalize_text(item.get("description")),
                content=normalize_text(item.get("content")),
                fetched_at_utc=fetched_at_utc,
                allowed_commodities=allowed_commodities,
            )
            continue
        conn.execute(
            """
            INSERT INTO news_articles (
                article_id,
                provider,
                commodity,
                source_name,
                published_at_utc,
                fetched_at_utc,
                title,
                description,
                content,
                url,
                language,
                query_text,
                story_id,
                raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                current_article_id,
                str(item.get("provider") or ""),
                commodity,
                normalize_text(item.get("source_name")),
                published_at_utc or fetched_at_utc,
                fetched_at_utc,
                title or "(untitled)",
                normalize_text(item.get("description")),
                normalize_text(item.get("content")),
                url,
                normalize_text(item.get("language") or "en"),
                query_text,
                current_story_id,
                safe_json(item.get("raw")),
            ),
        )
        upsert_article_links(
            conn,
            article_id=current_article_id,
            seed_commodity=commodity,
            title=title or "(untitled)",
            description=normalize_text(item.get("description")),
            content=normalize_text(item.get("content")),
            fetched_at_utc=fetched_at_utc,
            allowed_commodities=allowed_commodities,
        )
        inserted += 1
    conn.commit()
    return fetched, inserted


def score_new_articles(
    conn: sqlite3.Connection,
    scorer: ModelScorer,
    *,
    causal_profile: str,
) -> int:
    rows = conn.execute(
        """
        SELECT
            a.article_id,
            a.story_id,
            a.commodity,
            a.title,
            a.description,
            a.content
        FROM news_articles a
        LEFT JOIN news_scores s ON a.article_id = s.article_id
        WHERE s.article_id IS NULL
        ORDER BY a.published_at_utc DESC
        """
    ).fetchall()
    if not rows:
        return 0
    scored_at_utc = iso_utc(utc_now())
    story_cache: dict[str, dict[str, Any]] = {}
    for row in rows:
        current_article_id, current_story_id, commodity, title, description, content = row
        story_key = str(current_story_id or "").strip() or f"article:{current_article_id}"
        if story_key not in story_cache:
            story_cache[story_key] = scorer.score(
                commodity=str(commodity),
                title=str(title or ""),
                description=str(description or ""),
                content=str(content or ""),
            )
        score = story_cache[story_key]
        causal = analyze_causal_news(
            commodity=str(commodity),
            title=str(title or ""),
            description=str(description or ""),
            content=str(content or ""),
            direction=str(score.get("direction") or "hold"),
            reason_terms_up=score.get("reason_terms_up") or [],
            reason_terms_down=score.get("reason_terms_down") or [],
            profile=causal_profile,
        )
        severity = str(score["severity"]).lower()
        if severity not in SEVERITY_ORDER:
            severity = "medium"
        conn.execute(
            """
            INSERT OR REPLACE INTO news_scores (
                article_id,
                model_name,
                scored_at_utc,
                direction,
                impact_score,
                confidence,
                severity,
                reason_terms_up,
                reason_terms_down,
                cause_classification,
                cause_bucket,
                cause_event,
                transmission_channel,
                cause_cluster_key,
                cause_confidence,
                fundamental_score,
                direction_alignment,
                is_primary_cause,
                cause_route_key,
                cause_claim_status,
                cause_entities_json,
                cause_terms_json,
                effect_terms_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(current_article_id),
                str(score.get("model_name") or MODEL_NAME_KEYWORD),
                scored_at_utc,
                str(score["direction"]),
                float(score["impact_score"]),
                float(score["confidence"]),
                severity,
                safe_json(score.get("reason_terms_up") or []),
                safe_json(score.get("reason_terms_down") or []),
                str(causal.get("cause_classification") or "unknown"),
                str(causal.get("cause_bucket") or ""),
                str(causal.get("cause_event") or ""),
                str(causal.get("transmission_channel") or ""),
                str(causal.get("cause_cluster_key") or ""),
                float(causal.get("cause_confidence") or 0.0),
                float(causal.get("fundamental_score") or 0.0),
                float(causal.get("direction_alignment") or 0.5),
                1 if bool(causal.get("is_primary_cause")) else 0,
                str(causal.get("cause_route_key") or ""),
                str(causal.get("cause_claim_status") or "unknown"),
                safe_json(causal.get("cause_entities") or []),
                safe_json(causal.get("cause_terms") or []),
                safe_json(causal.get("effect_terms") or []),
            ),
        )
    conn.commit()
    return len(rows)


def upsert_article_links(
    conn: sqlite3.Connection,
    *,
    article_id: str,
    seed_commodity: str,
    title: str,
    description: str,
    content: str,
    fetched_at_utc: str,
    allowed_commodities: tuple[str, ...],
) -> None:
    allowed = {str(item or "").strip().upper() for item in allowed_commodities if str(item or "").strip()}
    if not allowed:
        return
    link_rows = [
        item
        for item in score_commodity_links(
            title=title,
            description=description,
            content=content,
            seed_commodities=[seed_commodity],
        )
        if item.commodity_id in allowed
    ]
    if not link_rows:
        return
    primary_commodity = next(
        (item.commodity_id for item in link_rows if item.is_primary),
        link_rows[0].commodity_id,
    )
    conn.execute(
        "UPDATE news_articles SET commodity = ? WHERE article_id = ?",
        (primary_commodity, str(article_id)),
    )
    for item in link_rows:
        conn.execute(
            """
            INSERT INTO news_article_commodity_links (
                article_id,
                commodity,
                link_score,
                link_reason,
                link_evidence_json,
                link_mode,
                is_primary_link,
                first_seen_at_utc,
                last_seen_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_id, commodity) DO UPDATE SET
                link_score = excluded.link_score,
                link_reason = excluded.link_reason,
                link_evidence_json = excluded.link_evidence_json,
                link_mode = excluded.link_mode,
                is_primary_link = excluded.is_primary_link,
                last_seen_at_utc = excluded.last_seen_at_utc
            """,
            (
                str(article_id),
                item.commodity_id,
                float(item.score),
                item.reason,
                safe_json(item.evidence_terms),
                item.link_mode,
                1 if item.is_primary else 0,
                fetched_at_utc,
                fetched_at_utc,
            ),
        )


def backfill_missing_causal(conn: sqlite3.Connection) -> int:
    return backfill_missing_causal_scores(conn)
