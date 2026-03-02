from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from moex_carry.storage.repositories import (
    load_news_entity_links,
    load_news_event_items,
    load_news_events,
    upsert_news_event_items,
    upsert_news_events,
)


_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "for",
    "in",
    "on",
    "at",
    "from",
    "by",
    "with",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "this",
    "that",
    "it",
    "its",
    "will",
    "has",
    "have",
    "had",
    "after",
    "amid",
    "into",
    "over",
    "under",
    "about",
    "new",
    "says",
    "say",
}

_UPDATE_PATTERNS = (
    r"\bupdate\b",
    r"\bupdated\b",
    r"\brevision\b",
    r"\brevised\b",
    r"\bfollow[- ]?up\b",
    r"\bcorrection\b",
    r"\bclarif(?:y|ies|ied)\b",
    r"\bобнов",
    r"\bапдейт",
)

_REFUTE_PATTERNS = (
    r"\brefut(?:e|ed|es)\b",
    r"\bden(?:y|ies|ied)\b",
    r"\bnot true\b",
    r"\bfalse\b",
    r"\brumou?r denied\b",
    r"\bопроверж",
    r"\bопроверг",
)


@dataclass(frozen=True)
class EventClusteringReport:
    processed_news: int
    linked_news: int
    created_events: int
    updated_events: int
    refuted_events: int
    resolved_events: int
    duplicate_links: int
    update_links: int
    refute_links: int
    primary_links: int
    cluster_version: str


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _normalize_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").lower()).strip()
    return text


def _tokenize(value: str, *, max_tokens: int = 20) -> set[str]:
    text = _normalize_text(value)
    raw_tokens = re.findall(r"[a-z0-9]{3,}", text)
    tokens: list[str] = []
    for token in raw_tokens:
        if token in _STOPWORDS:
            continue
        tokens.append(token)
        if len(tokens) >= max_tokens:
            break
    return set(tokens)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return float(len(left & right)) / float(len(union))


def _detect_link_role(text: str) -> str:
    normalized = _normalize_text(text)
    for pattern in _REFUTE_PATTERNS:
        if re.search(pattern, normalized):
            return "refute"
    for pattern in _UPDATE_PATTERNS:
        if re.search(pattern, normalized):
            return "update"
    return "primary"


def _build_event_id(
    *,
    published_at: datetime,
    commodity_ids: Iterable[str],
    title: str,
    cluster_window_hours: int,
) -> str:
    commodities = sorted({str(item).strip().upper() for item in commodity_ids if str(item).strip()})
    commodity_key = ",".join(commodities) if commodities else "UNKNOWN"
    title_tokens = sorted(_tokenize(title, max_tokens=6))
    topic_key = "-".join(title_tokens[:4]) if title_tokens else "misc"
    window_sec = max(int(cluster_window_hours), 1) * 3600
    epoch = datetime(1970, 1, 1)
    bucket = int((published_at - epoch).total_seconds() // window_sec)
    raw = f"{commodity_key}|{topic_key}|{bucket}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"evt-{digest}"


def _event_status_transition(current_status: str, link_role: str) -> str:
    normalized_status = str(current_status or "active").strip().lower() or "active"
    if link_role == "refute":
        return "refuted"
    if link_role in {"update", "duplicate"} and normalized_status in {"active", "updated"}:
        return "updated"
    if normalized_status in {"resolved", "refuted"}:
        return normalized_status
    return normalized_status


def _safe_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() + "Z"


def _build_fragmentation_report(
    *,
    event_rows: list[dict[str, object]],
    event_item_rows: list[dict[str, object]],
) -> dict[str, object]:
    news_count_by_event: dict[str, int] = {}
    role_counts = {"primary": 0, "duplicate": 0, "update": 0, "refute": 0}
    for row in event_item_rows:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            continue
        news_count_by_event[event_id] = int(news_count_by_event.get(event_id, 0)) + 1
        role = str(row.get("link_role") or "primary").strip().lower() or "primary"
        if role in role_counts:
            role_counts[role] = int(role_counts[role]) + 1
    total_events = len(event_rows)
    singleton_events = sum(1 for count in news_count_by_event.values() if count <= 1)
    multi_news_events = sum(1 for count in news_count_by_event.values() if count > 1)
    total_links = sum(news_count_by_event.values())
    avg_news_per_event = (float(total_links) / float(total_events)) if total_events > 0 else 0.0
    fragmentation_ratio = (float(singleton_events) / float(total_events)) if total_events > 0 else 0.0
    return {
        "events_total": total_events,
        "event_links_total": total_links,
        "singleton_events": singleton_events,
        "multi_news_events": multi_news_events,
        "avg_news_per_event": avg_news_per_event,
        "fragmentation_ratio": fragmentation_ratio,
        "role_counts": role_counts,
    }


def compute_event_fragmentation_report(
    session: Session,
    *,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
) -> dict[str, object]:
    event_rows = load_news_events(
        session,
        published_from=_safe_iso(published_from),
        published_to=_safe_iso(published_to),
        limit=0,
    )
    event_ids = [str(row.get("event_id") or "").strip() for row in event_rows if row.get("event_id")]
    event_item_rows = load_news_event_items(session, event_ids=event_ids, limit=0) if event_ids else []
    return _build_fragmentation_report(event_rows=event_rows, event_item_rows=event_item_rows)


def cluster_news_events(
    session: Session,
    *,
    news_rows: list[dict[str, object]],
    cluster_window_hours: int = 48,
    similarity_threshold: float = 0.35,
    resolve_after_hours: int = 72,
    cluster_version: str = "det-v1",
    commit: bool = True,
) -> EventClusteringReport:
    normalized_news: list[dict[str, object]] = []
    for row in news_rows:
        if not isinstance(row, dict):
            continue
        news_id = str(row.get("news_id") or "").strip()
        published_at = _parse_datetime(row.get("published_at"))
        if not news_id or published_at is None:
            continue
        normalized_news.append({**row, "_published_at": published_at})

    if not normalized_news:
        return EventClusteringReport(
            processed_news=0,
            linked_news=0,
            created_events=0,
            updated_events=0,
            refuted_events=0,
            resolved_events=0,
            duplicate_links=0,
            update_links=0,
            refute_links=0,
            primary_links=0,
            cluster_version=cluster_version,
        )

    normalized_news.sort(key=lambda item: item["_published_at"])
    news_ids = [str(item.get("news_id") or "") for item in normalized_news]
    news_links = load_news_event_items(session, news_ids=news_ids, limit=max(len(news_ids) * 2, 1000))
    already_linked_news = {str(row.get("news_id") or "").strip() for row in news_links}
    unlinked_news = [item for item in normalized_news if str(item.get("news_id") or "") not in already_linked_news]

    if not unlinked_news:
        return EventClusteringReport(
            processed_news=len(normalized_news),
            linked_news=len(normalized_news),
            created_events=0,
            updated_events=0,
            refuted_events=0,
            resolved_events=0,
            duplicate_links=0,
            update_links=0,
            refute_links=0,
            primary_links=0,
            cluster_version=cluster_version,
        )

    source_entity_rows = load_news_entity_links(session, news_ids=news_ids, limit=max(len(news_ids) * 8, 2000))
    commodities_by_news: dict[str, set[str]] = {}
    for row in source_entity_rows:
        if not isinstance(row, dict):
            continue
        news_id = str(row.get("news_id") or "").strip()
        ticker = str(row.get("ticker") or row.get("entity_id") or "").strip().upper()
        if not news_id or not ticker:
            continue
        commodities_by_news.setdefault(news_id, set()).add(ticker)

    min_published = min(item["_published_at"] for item in unlinked_news)
    max_published = max(item["_published_at"] for item in unlinked_news)
    padded_from = min_published - timedelta(hours=max(cluster_window_hours, 1))
    padded_to = max_published + timedelta(hours=max(cluster_window_hours, 1))
    candidate_events = load_news_events(
        session,
        published_from=_safe_iso(padded_from),
        published_to=_safe_iso(padded_to),
        limit=0,
    )
    candidate_event_ids = [str(item.get("event_id") or "").strip() for item in candidate_events if item.get("event_id")]
    candidate_event_items = (
        load_news_event_items(session, event_ids=candidate_event_ids, limit=0) if candidate_event_ids else []
    )
    candidate_event_news_ids = sorted(
        {
            str(item.get("news_id") or "").strip()
            for item in candidate_event_items
            if str(item.get("news_id") or "").strip()
        }
    )
    candidate_entities = (
        load_news_entity_links(
            session,
            news_ids=candidate_event_news_ids,
            limit=max(len(candidate_event_news_ids) * 8, 4000),
        )
        if candidate_event_news_ids
        else []
    )
    event_commodities: dict[str, set[str]] = {}
    news_to_events: dict[str, set[str]] = {}
    for item in candidate_event_items:
        event_id = str(item.get("event_id") or "").strip()
        news_id = str(item.get("news_id") or "").strip()
        if not event_id or not news_id:
            continue
        news_to_events.setdefault(news_id, set()).add(event_id)
    for row in candidate_entities:
        news_id = str(row.get("news_id") or "").strip()
        ticker = str(row.get("ticker") or row.get("entity_id") or "").strip().upper()
        if not news_id or not ticker:
            continue
        for event_id in news_to_events.get(news_id, set()):
            event_commodities.setdefault(event_id, set()).add(ticker)

    event_states: dict[str, dict[str, object]] = {}
    for row in candidate_events:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            continue
        summary = str(row.get("canonical_summary") or "").strip()
        mechanism = str(row.get("canonical_mechanism") or "").strip()
        last_published = _parse_datetime(
            row.get("event_last_published_at_utc") or row.get("event_first_published_at_utc")
        )
        if last_published is None:
            continue
        tokens = _tokenize(f"{summary} {mechanism}")
        event_states[event_id] = {
            "event_id": event_id,
            "event_first_published_at_utc": row.get("event_first_published_at_utc"),
            "event_first_ingested_at_utc": row.get("event_first_ingested_at_utc"),
            "event_last_published_at_utc": _safe_iso(last_published),
            "event_status": str(row.get("event_status") or "active"),
            "canonical_summary": summary,
            "canonical_mechanism": mechanism,
            "cluster_version": str(row.get("cluster_version") or cluster_version),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "_last_published": last_published,
            "_tokens": tokens,
            "_commodities": set(event_commodities.get(event_id, set())),
        }

    upsert_events: dict[str, dict[str, object]] = {}
    upsert_event_items: list[dict[str, object]] = []

    created_events = 0
    updated_events = 0
    refuted_events = 0
    duplicate_links = 0
    update_links = 0
    refute_links = 0
    primary_links = 0

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    window_delta = timedelta(hours=max(cluster_window_hours, 1))

    for news in unlinked_news:
        news_id = str(news.get("news_id") or "").strip()
        title = str(news.get("title") or "").strip()
        content = str(news.get("content") or "").strip()
        published_at = news["_published_at"]
        ingested_at = _parse_datetime(news.get("ingested_at")) or now
        news_tokens = _tokenize(f"{title} {content}")
        link_role_hint = _detect_link_role(f"{title} {content}")
        news_commodities = set(commodities_by_news.get(news_id, set()))
        if not news_commodities:
            news_commodities = {"UNKNOWN"}
        matched_event_id: str | None = None
        matched_similarity = 0.0

        for event_id, state in event_states.items():
            last_published = state.get("_last_published")
            if not isinstance(last_published, datetime):
                continue
            if math.fabs((published_at - last_published).total_seconds()) > window_delta.total_seconds():
                continue
            state_commodities = state.get("_commodities")
            if isinstance(state_commodities, set):
                if "UNKNOWN" not in state_commodities and "UNKNOWN" not in news_commodities:
                    if state_commodities.isdisjoint(news_commodities):
                        continue
            state_tokens = state.get("_tokens")
            if not isinstance(state_tokens, set):
                state_tokens = set()
            similarity = _jaccard(news_tokens, state_tokens)
            min_similarity = 0.0 if link_role_hint in {"update", "refute"} else similarity_threshold
            if similarity < min_similarity:
                continue
            if similarity > matched_similarity:
                matched_similarity = similarity
                matched_event_id = event_id

        if matched_event_id is None:
            event_id = _build_event_id(
                published_at=published_at,
                commodity_ids=news_commodities,
                title=title,
                cluster_window_hours=cluster_window_hours,
            )
            if event_id in event_states:
                fallback_raw = f"{event_id}|{news_id}"
                digest = hashlib.sha1(fallback_raw.encode("utf-8")).hexdigest()[:10]
                event_id = f"{event_id}-{digest}"
            link_role = "refute" if link_role_hint == "refute" else "primary"
            status = "refuted" if link_role == "refute" else "active"
            canonical_summary = title or f"event {event_id}"
            canonical_mechanism = (
                f"Deterministic cluster ({cluster_version}) from headline/topic match for "
                f"{','.join(sorted(news_commodities))}."
            )
            event_payload = {
                "event_id": event_id,
                "event_first_published_at_utc": _safe_iso(published_at),
                "event_first_ingested_at_utc": _safe_iso(ingested_at),
                "event_last_published_at_utc": _safe_iso(published_at),
                "event_status": status,
                "canonical_summary": canonical_summary,
                "canonical_mechanism": canonical_mechanism,
                "cluster_version": cluster_version,
                "created_at": _safe_iso(now),
                "updated_at": _safe_iso(now),
            }
            event_states[event_id] = {
                **event_payload,
                "_last_published": published_at,
                "_tokens": set(news_tokens),
                "_commodities": set(news_commodities),
            }
            upsert_events[event_id] = event_payload
            created_events += 1
            if link_role == "primary":
                primary_links += 1
            else:
                refute_links += 1
                refuted_events += 1
            upsert_event_items.append(
                {
                    "event_id": event_id,
                    "news_id": news_id,
                    "link_role": link_role,
                    "similarity_score": matched_similarity,
                    "added_at": _safe_iso(now),
                }
            )
            continue

        state = event_states[matched_event_id]
        current_status = str(state.get("event_status") or "active")
        link_role = link_role_hint
        if matched_similarity >= 0.75 and link_role == "primary":
            link_role = "duplicate"
        next_status = _event_status_transition(current_status, link_role)
        if next_status == "updated" and current_status != "updated":
            updated_events += 1
        if next_status == "refuted" and current_status != "refuted":
            refuted_events += 1
        if link_role == "duplicate":
            duplicate_links += 1
        elif link_role == "update":
            update_links += 1
        elif link_role == "refute":
            refute_links += 1
        else:
            primary_links += 1

        last_published = state.get("_last_published")
        if isinstance(last_published, datetime):
            effective_last = max(last_published, published_at)
        else:
            effective_last = published_at
        state["_last_published"] = effective_last
        state["_tokens"] = set(state.get("_tokens") or set()) | news_tokens
        state["_commodities"] = set(state.get("_commodities") or set()) | news_commodities
        if not str(state.get("canonical_summary") or "").strip():
            state["canonical_summary"] = title or str(state.get("event_id") or "")
        if not str(state.get("canonical_mechanism") or "").strip():
            state["canonical_mechanism"] = (
                f"Deterministic cluster ({cluster_version}) from headline/topic match."
            )
        state["event_status"] = next_status
        state["event_last_published_at_utc"] = _safe_iso(effective_last)
        state["updated_at"] = _safe_iso(now)
        upsert_events[matched_event_id] = {
            "event_id": matched_event_id,
            "event_first_published_at_utc": state.get("event_first_published_at_utc"),
            "event_first_ingested_at_utc": state.get("event_first_ingested_at_utc"),
            "event_last_published_at_utc": state.get("event_last_published_at_utc"),
            "event_status": state.get("event_status"),
            "canonical_summary": state.get("canonical_summary"),
            "canonical_mechanism": state.get("canonical_mechanism"),
            "cluster_version": state.get("cluster_version") or cluster_version,
            "created_at": state.get("created_at"),
            "updated_at": state.get("updated_at"),
        }
        upsert_event_items.append(
            {
                "event_id": matched_event_id,
                "news_id": news_id,
                "link_role": link_role,
                "similarity_score": matched_similarity,
                "added_at": _safe_iso(now),
            }
        )

    resolved_events = 0
    resolution_cutoff = now - timedelta(hours=max(resolve_after_hours, 1))
    for event_id, state in event_states.items():
        status = str(state.get("event_status") or "active").lower()
        last_published = state.get("_last_published")
        if status not in {"active", "updated"}:
            continue
        if not isinstance(last_published, datetime):
            continue
        if last_published >= resolution_cutoff:
            continue
        state["event_status"] = "resolved"
        state["updated_at"] = _safe_iso(now)
        upsert_events[event_id] = {
            "event_id": event_id,
            "event_first_published_at_utc": state.get("event_first_published_at_utc"),
            "event_first_ingested_at_utc": state.get("event_first_ingested_at_utc"),
            "event_last_published_at_utc": state.get("event_last_published_at_utc"),
            "event_status": "resolved",
            "canonical_summary": state.get("canonical_summary"),
            "canonical_mechanism": state.get("canonical_mechanism"),
            "cluster_version": state.get("cluster_version") or cluster_version,
            "created_at": state.get("created_at"),
            "updated_at": state.get("updated_at"),
        }
        resolved_events += 1

    if upsert_events:
        upsert_news_events(session, upsert_events.values(), commit=commit)
    if upsert_event_items:
        upsert_news_event_items(session, upsert_event_items, commit=commit)

    return EventClusteringReport(
        processed_news=len(normalized_news),
        linked_news=len(upsert_event_items) + len(already_linked_news),
        created_events=created_events,
        updated_events=updated_events,
        refuted_events=refuted_events,
        resolved_events=resolved_events,
        duplicate_links=duplicate_links,
        update_links=update_links,
        refute_links=refute_links,
        primary_links=primary_links,
        cluster_version=cluster_version,
    )
