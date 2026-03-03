from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests


_GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
_NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_any_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    raw = str(value).strip()
    if not raw:
        return None
    parsed = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_url(value: object) -> str:
    url = _normalize_text(value)
    if not url:
        return ""
    lowered = url.lower()
    for marker in ("?utm_", "&utm_", "?fbclid=", "&fbclid="):
        idx = lowered.find(marker)
        if idx >= 0:
            return url[:idx]
    return url


def _dt_to_gdelt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


def _dt_to_newsapi(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_gdelt_articles(
    session: requests.Session,
    *,
    query: str,
    start_utc: datetime,
    end_utc: datetime,
    max_records: int,
    timeout_sec: float,
) -> list[dict[str, Any]]:
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "sort": "DateDesc",
        "maxrecords": max_records,
        "startdatetime": _dt_to_gdelt(start_utc),
        "enddatetime": _dt_to_gdelt(end_utc),
    }
    response = session.get(_GDELT_ENDPOINT, params=params, timeout=timeout_sec)
    response.raise_for_status()
    payload = response.json()
    articles = payload.get("articles")
    if not isinstance(articles, list):
        return []
    output: list[dict[str, Any]] = []
    for item in articles:
        if not isinstance(item, dict):
            continue
        published = _parse_any_utc(item.get("seendate")) or _utc_now()
        output.append(
            {
                "provider": "gdelt",
                "published_at_utc": _iso_utc(published),
                "source_name": _normalize_text(item.get("domain") or "gdelt"),
                "title": _normalize_text(item.get("title")),
                "description": _normalize_text(item.get("snippet")),
                "content": "",
                "url": _normalize_url(item.get("url")),
                "language": _normalize_text(item.get("language") or "en"),
                "raw": item,
            }
        )
    return output


def fetch_newsapi_articles(
    session: requests.Session,
    *,
    api_key: str,
    query: str,
    start_utc: datetime,
    end_utc: datetime,
    language: str,
    page_size: int,
    sort_by: str,
    timeout_sec: float,
) -> list[dict[str, Any]]:
    headers = {"X-Api-Key": api_key}
    params = {
        "q": query,
        "from": _dt_to_newsapi(start_utc),
        "to": _dt_to_newsapi(end_utc),
        "language": language or "en",
        "sortBy": sort_by,
        "pageSize": max(1, min(page_size, 100)),
        "page": 1,
    }
    response = session.get(_NEWSAPI_ENDPOINT, params=params, headers=headers, timeout=timeout_sec)
    response.raise_for_status()
    payload = response.json()
    articles = payload.get("articles")
    if not isinstance(articles, list):
        return []
    output: list[dict[str, Any]] = []
    for item in articles:
        if not isinstance(item, dict):
            continue
        published = _parse_any_utc(item.get("publishedAt")) or _utc_now()
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        output.append(
            {
                "provider": "newsapi",
                "published_at_utc": _iso_utc(published),
                "source_name": _normalize_text(source.get("name") or "newsapi"),
                "title": _normalize_text(item.get("title")),
                "description": _normalize_text(item.get("description")),
                "content": _normalize_text(item.get("content")),
                "url": _normalize_url(item.get("url")),
                "language": _normalize_text(language or "en"),
                "raw": item,
            }
        )
    return output

