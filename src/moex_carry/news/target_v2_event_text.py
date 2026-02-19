from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from moex_carry.storage.repositories import load_news_items_by_ids


_TICKER_SUPPORT_TERMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # (topic_terms, market_anchor_terms)
    "NG_US": (
        (
            "natural gas",
            "henry hub",
            "nymex",
            "lng",
            "feedgas",
            "gas storage",
            "eia storage",
            "withdrawal",
            "injection",
            "freeze-off",
            "pipeline",
            "hdd",
            "cdd",
        ),
        (
            "united states",
            "u.s.",
            " usa ",
            "us ",
            " eia ",
            "henry hub",
            "nymex",
            "freeport",
            "sabine",
            "bcf",
            "texas",
            "louisiana",
            "appalachia",
            "permian",
        ),
    ),
}


def _parse_iso_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def build_event_text_by_id(
    session: Session,
    *,
    event_to_news: dict[str, list[str]],
    max_chars: int = 6000,
) -> dict[str, str]:
    news_ids = sorted(
        {
            news_id
            for rows in event_to_news.values()
            for news_id in rows
            if isinstance(news_id, str) and news_id
        }
    )
    if not news_ids:
        return {}
    news_rows = load_news_items_by_ids(session, news_ids)
    news_by_id = {str(row.get("news_id") or "").strip(): row for row in news_rows}
    result: dict[str, str] = {}
    for event_id, rows in event_to_news.items():
        fragments: list[str] = []
        for news_id in rows[:10]:
            item = news_by_id.get(str(news_id or "").strip())
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            content = str(item.get("content") or "").strip()
            if title:
                fragments.append(title)
            if content:
                fragments.append(content[:500])
        text = " | ".join(fragment for fragment in fragments if fragment).lower()
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars]
        result[event_id] = text
    return result


def ticker_has_text_support(*, ticker: str, text: str) -> bool:
    normalized_ticker = str(ticker or "").strip().upper()
    spec = _TICKER_SUPPORT_TERMS.get(normalized_ticker)
    if spec is None:
        return True
    topic_terms, anchor_terms = spec
    lowered = f" {str(text or '').lower()} "

    def _contains(term: str) -> bool:
        needle = str(term or "").strip().lower()
        if not needle:
            return False
        if " " in needle or "-" in needle or "/" in needle:
            return needle in lowered
        pattern = rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])"
        return re.search(pattern, lowered) is not None

    topic_hits = sum(1 for term in topic_terms if _contains(term))
    anchor_hits = sum(1 for term in anchor_terms if _contains(term))
    return bool(topic_hits >= 1 and anchor_hits >= 1)


def build_event_echo_scores(
    session: Session,
    *,
    event_to_news: dict[str, list[str]],
    delay_minutes: int = 45,
) -> dict[str, float]:
    news_ids = sorted(
        {
            news_id
            for rows in event_to_news.values()
            for news_id in rows
            if isinstance(news_id, str) and news_id
        }
    )
    if not news_ids:
        return {}
    news_rows = load_news_items_by_ids(session, news_ids)
    news_by_id = {str(row.get("news_id") or "").strip(): row for row in news_rows}
    min_delay = timedelta(minutes=max(int(delay_minutes), 1))
    scores: dict[str, float] = {}
    for event_id, rows in event_to_news.items():
        published_points: list[tuple[str, str, object]] = []
        for news_id in rows:
            row = news_by_id.get(str(news_id or "").strip())
            if not isinstance(row, dict):
                continue
            source = str(row.get("source") or "").strip().lower()
            published_at = _parse_iso_datetime(row.get("published_at"))
            if source and published_at is not None:
                published_points.append((str(news_id), source, published_at))
        if not published_points:
            scores[event_id] = 0.0
            continue
        published_points.sort(key=lambda item: item[2])
        first_ts = published_points[0][2]
        delayed = 0
        commentary = 0
        for _, source, ts in published_points[1:]:
            if ts - first_ts >= min_delay:
                delayed += 1
            if any(token in source for token in ("blog", "opinion", "analysis", "newsletter", "finance.yahoo")):
                commentary += 1
        denom = max(len(published_points) - 1, 1)
        echo_ratio = delayed / float(denom)
        commentary_ratio = commentary / float(max(len(published_points), 1))
        scores[event_id] = max(0.0, min(1.0, 0.7 * echo_ratio + 0.3 * commentary_ratio))
    return scores
