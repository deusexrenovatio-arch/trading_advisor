from __future__ import annotations

import json
import sqlite3

from moex_carry.news_causal import analyze_causal_news
from moex_carry.news_commodity_graph import build_event_first_query_terms


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _safe_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


def _json_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    raw = str(value or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def augment_query_with_event_terms(query_text: str, *, commodity: str, max_terms: int) -> str:
    base = _normalize_text(query_text)
    extra_terms = build_event_first_query_terms(commodity, max_terms=max_terms)
    if not extra_terms:
        return base
    quoted = [f"\"{_normalize_text(term)}\"" for term in extra_terms if _normalize_text(term)]
    if not quoted:
        return base
    event_block = " OR ".join(quoted)
    if not base:
        return f"({event_block})"
    return f"({base}) OR ({event_block})"


def backfill_missing_causal_scores(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT
            s.article_id,
            a.commodity,
            a.title,
            a.description,
            a.content,
            s.direction,
            s.reason_terms_up,
            s.reason_terms_down
        FROM news_scores s
        JOIN news_articles a ON a.article_id = s.article_id
        WHERE
            COALESCE(TRIM(s.cause_classification), '') = ''
            OR LOWER(COALESCE(TRIM(s.cause_classification), '')) = 'unknown'
            OR COALESCE(TRIM(s.cause_cluster_key), '') = ''
            OR s.fundamental_score IS NULL
            OR COALESCE(TRIM(s.cause_claim_status), '') = ''
            OR s.cause_entities_json IS NULL
        ORDER BY a.published_at_utc DESC
        """
    ).fetchall()
    if not rows:
        return 0
    for article_id, commodity, title, description, content, direction, terms_up_raw, terms_down_raw in rows:
        causal = analyze_causal_news(
            commodity=str(commodity or ""),
            title=str(title or ""),
            description=str(description or ""),
            content=str(content or ""),
            direction=str(direction or "hold"),
            reason_terms_up=_json_list(terms_up_raw),
            reason_terms_down=_json_list(terms_down_raw),
        )
        conn.execute(
            """
            UPDATE news_scores
            SET
                cause_classification = ?,
                cause_bucket = ?,
                cause_event = ?,
                transmission_channel = ?,
                cause_cluster_key = ?,
                cause_confidence = ?,
                fundamental_score = ?,
                direction_alignment = ?,
                is_primary_cause = ?,
                cause_route_key = ?,
                cause_claim_status = ?,
                cause_entities_json = ?,
                cause_terms_json = ?,
                effect_terms_json = ?
            WHERE article_id = ?
            """,
            (
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
                _safe_json(causal.get("cause_entities") or []),
                _safe_json(causal.get("cause_terms") or []),
                _safe_json(causal.get("effect_terms") or []),
                str(article_id),
            ),
        )
    conn.commit()
    return len(rows)

