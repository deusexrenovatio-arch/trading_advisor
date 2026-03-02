from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from moex_carry.domain.decision import NewsItem
from moex_carry.news.taxonomy import impact_to_severity
from moex_carry.strategy.news_filter import NewsGateResult, apply_news_filter


def build_news_items_for_gate(
    rows: Iterable[dict[str, object]],
    *,
    score_by_news: dict[str, dict[str, object]],
) -> list[NewsItem]:
    items: list[NewsItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        news_id = str(row.get("news_id") or "").strip()
        published_at_raw = row.get("published_at")
        if not news_id or published_at_raw is None:
            continue
        try:
            published_at = datetime.fromisoformat(str(published_at_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)

        score = score_by_news.get(news_id) or {}
        impact_score = float(score.get("impact_score") or 0.0)
        severity = impact_to_severity(impact_score)
        title = str(row.get("title") or "news")
        source = str(row.get("source") or "unknown")
        items.append(
            NewsItem(
                item_id=news_id,
                timestamp=published_at,
                source=source,
                title=title,
                severity=severity,
                impact_score=impact_score,
            )
        )
    return items


def run_news_gate(
    rows: Iterable[dict[str, object]],
    *,
    score_by_news: dict[str, dict[str, object]],
    lookback_minutes: int,
    block_severity_threshold: str,
    reduce_severity_threshold: str,
    allowed_sources: Iterable[str] | None = None,
    enforce_source_allowlist: bool = False,
) -> NewsGateResult:
    items = build_news_items_for_gate(rows, score_by_news=score_by_news)
    return apply_news_filter(
        items,
        lookback_minutes=lookback_minutes,
        block_severity_threshold=block_severity_threshold,
        reduce_severity_threshold=reduce_severity_threshold,
        allowed_sources=allowed_sources,
        enforce_source_allowlist=enforce_source_allowlist,
    )


def build_signal_news_links(
    *,
    signal_id: str | None,
    decision_id: str | None,
    matched_news_ids: Iterable[str] | None = None,
    matched_news_refs: Iterable[dict[str, object]] | None = None,
    gate_action: str,
    link_type: str,
    lookback_minutes: int,
    source: str = "runtime",
) -> list[dict[str, object]]:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=max(int(lookback_minutes), 1))
    links: list[dict[str, object]] = []
    refs: list[tuple[str, str | None]] = []
    for news_id in matched_news_ids or []:
        normalized_news_id = str(news_id or "").strip()
        if not normalized_news_id:
            continue
        refs.append((normalized_news_id, None))
    for row in matched_news_refs or []:
        if not isinstance(row, dict):
            continue
        normalized_news_id = str(row.get("news_id") or "").strip()
        if not normalized_news_id:
            continue
        event_id = str(row.get("event_id") or "").strip() or None
        refs.append((normalized_news_id, event_id))

    deduped: dict[tuple[str, str | None], None] = {}
    for item in refs:
        deduped[item] = None

    for normalized_news_id, event_id in deduped:
        links.append(
            {
                "news_id": normalized_news_id,
                "event_id": event_id,
                "signal_id": signal_id,
                "decision_id": decision_id,
                "link_type": link_type,
                "window_start": window_start.isoformat().replace("+00:00", "Z"),
                "window_end": now.isoformat().replace("+00:00", "Z"),
                "gate_action": gate_action,
                "source": source,
                "created_at": now.isoformat().replace("+00:00", "Z"),
            }
        )
    return links
