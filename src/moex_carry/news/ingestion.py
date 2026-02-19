from __future__ import annotations

import hashlib
import importlib
import re
import time
from datetime import datetime, timezone
from typing import Iterable

import requests


_LAST_GDELT_REQUEST_AT: float | None = None

def _safe_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def normalize_article_text(raw_text: str | None) -> str:
    text = str(raw_text or "")
    if not text:
        return ""
    looks_like_html = "<" in text and ">" in text
    trafilatura = _safe_import("trafilatura")
    if trafilatura is not None and looks_like_html:
        try:
            extracted = trafilatura.extract(text, include_comments=False, include_tables=False)
            if isinstance(extracted, str) and extracted.strip():
                text = extracted
        except Exception:
            pass

    bs4 = _safe_import("bs4")
    if bs4 is not None:
        try:
            soup = bs4.BeautifulSoup(text, "html.parser")
            text = soup.get_text(" ", strip=True)
        except Exception:
            pass

    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_published_at(raw_value: object) -> datetime:
    if isinstance(raw_value, datetime):
        dt = raw_value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    raw = str(raw_value or "").strip()
    if not raw:
        return datetime.now(timezone.utc)

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass

    dateparser = _safe_import("dateparser")
    if dateparser is not None:
        parsed = dateparser.parse(raw)
        if isinstance(parsed, datetime):
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

    return datetime.now(timezone.utc)


def normalize_news_record(raw_item: dict[str, object], *, source: str | None = None) -> dict[str, object] | None:
    title = str(raw_item.get("title") or "").strip()
    url = str(raw_item.get("url") or raw_item.get("link") or "").strip() or None
    content_raw = raw_item.get("content") or raw_item.get("summary") or raw_item.get("description")
    content = normalize_article_text(str(content_raw or ""))
    if not title and not content:
        return None

    published_at = parse_published_at(raw_item.get("published_at") or raw_item.get("published"))
    language = str(raw_item.get("language") or "").strip().lower() or None
    source_value = str(source or raw_item.get("source") or "rss").strip() or "rss"

    hash_input = "|".join(
        [
            source_value.lower(),
            str(url or "").lower(),
            title.lower(),
            published_at.isoformat(),
        ]
    )
    digest = hashlib.sha1(hash_input.encode("utf-8")).hexdigest()
    return {
        "news_id": f"news-{digest[:20]}",
        "source": source_value,
        "url": url,
        "title": title or content[:120],
        "content": content or None,
        "language": language,
        "published_at": published_at.isoformat().replace("+00:00", "Z"),
        "ingested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "hash": digest,
    }


def fetch_rss_news(urls: Iterable[str], *, max_items: int = 200) -> list[dict[str, object]]:
    feedparser = _safe_import("feedparser")
    if feedparser is None:
        return []

    collected: list[dict[str, object]] = []
    for url in urls:
        if len(collected) >= max_items:
            break
        try:
            parsed = feedparser.parse(url)
        except Exception:
            continue
        entries = parsed.get("entries") if isinstance(parsed, dict) else getattr(parsed, "entries", [])
        for entry in entries or []:
            if len(collected) >= max_items:
                break
            payload = {
                "title": entry.get("title"),
                "summary": entry.get("summary"),
                "description": entry.get("description"),
                "published": entry.get("published"),
                "link": entry.get("link"),
                "language": entry.get("language"),
            }
            normalized = normalize_news_record(payload, source=str(url))
            if normalized is not None:
                collected.append(normalized)
    return collected


def _format_gdelt_datetime(value: datetime) -> str:
    normalized = value
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    else:
        normalized = normalized.astimezone(timezone.utc)
    return normalized.strftime("%Y%m%d%H%M%S")


def _format_iso_datetime(value: datetime) -> str:
    normalized = value
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    else:
        normalized = normalized.astimezone(timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")


def _respect_gdelt_rate_limit(min_interval_sec: float) -> None:
    global _LAST_GDELT_REQUEST_AT
    now = time.monotonic()
    if _LAST_GDELT_REQUEST_AT is None:
        _LAST_GDELT_REQUEST_AT = now
        return
    delay = float(min_interval_sec) - (now - _LAST_GDELT_REQUEST_AT)
    if delay > 0.0:
        time.sleep(delay)
    _LAST_GDELT_REQUEST_AT = time.monotonic()


def fetch_gdelt_news(
    *,
    query: str,
    start_dt: datetime,
    end_dt: datetime,
    max_items: int = 250,
    min_request_interval_sec: float = 5.2,
    timeout_sec: int = 40,
    retries: int = 2,
    retry_backoff_sec: float = 2.0,
) -> list[dict[str, object]]:
    query_value = str(query or "").strip()
    if not query_value:
        return []
    effective_max = min(max(int(max_items), 1), 250)
    _respect_gdelt_rate_limit(max(float(min_request_interval_sec), 0.0))

    params = {
        "query": query_value,
        "mode": "ArtList",
        "maxrecords": str(effective_max),
        "format": "json",
        "sort": "DateDesc",
        "startdatetime": _format_gdelt_datetime(start_dt),
        "enddatetime": _format_gdelt_datetime(end_dt),
    }
    response = None
    attempts = max(int(retries), 0) + 1
    for attempt in range(attempts):
        try:
            response = requests.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params=params,
                timeout=max(int(timeout_sec), 5),
            )
        except requests.RequestException:
            response = None
        if response is not None and response.status_code == 200:
            break
        if attempt < attempts - 1:
            if response is not None and response.status_code == 429:
                time.sleep(max(float(min_request_interval_sec), 5.0))
            else:
                time.sleep(max(float(retry_backoff_sec), 0.0) * (attempt + 1))

    if response is None or response.status_code != 200:
        return []

    try:
        payload = response.json()
    except ValueError:
        return []

    articles = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(articles, list):
        return []

    collected: list[dict[str, object]] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        normalized = normalize_news_record(
            {
                "title": article.get("title"),
                "summary": article.get("title"),
                "description": article.get("description"),
                "published": article.get("seendate"),
                "link": article.get("url"),
                "language": article.get("language"),
                "source": article.get("domain"),
            },
            source="gdelt",
        )
        if normalized is None:
            continue
        collected.append(normalized)
    return collected


def fetch_newsapi_news(
    *,
    query: str,
    start_dt: datetime,
    end_dt: datetime,
    api_key: str,
    base_url: str = "https://newsapi.org/v2/everything",
    page: int = 1,
    page_size: int = 100,
    timeout_sec: int = 30,
    language: str | None = "en",
    sort_by: str = "publishedAt",
    domains: Iterable[str] | None = None,
) -> list[dict[str, object]]:
    query_value = str(query or "").strip()
    key_value = str(api_key or "").strip()
    if not query_value or not key_value:
        return []

    url = str(base_url or "").strip() or "https://newsapi.org/v2/everything"
    effective_page = max(int(page), 1)
    effective_page_size = min(max(int(page_size), 1), 100)
    params: dict[str, str] = {
        "q": query_value,
        "from": _format_iso_datetime(start_dt),
        "to": _format_iso_datetime(end_dt),
        "sortBy": str(sort_by or "publishedAt"),
        "pageSize": str(effective_page_size),
        "page": str(effective_page),
    }
    language_value = str(language or "").strip()
    if language_value:
        params["language"] = language_value
    domain_values = [str(item or "").strip() for item in (domains or []) if str(item or "").strip()]
    if domain_values:
        params["domains"] = ",".join(domain_values)

    try:
        response = requests.get(
            url,
            params=params,
            headers={"X-Api-Key": key_value},
            timeout=max(int(timeout_sec), 5),
        )
    except requests.RequestException:
        return []

    if response.status_code != 200:
        return []

    try:
        payload = response.json()
    except ValueError:
        return []

    if not isinstance(payload, dict):
        return []
    if str(payload.get("status") or "").strip().lower() != "ok":
        return []

    articles = payload.get("articles")
    if not isinstance(articles, list):
        return []

    collected: list[dict[str, object]] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        source_payload = article.get("source") if isinstance(article.get("source"), dict) else {}
        source_name = str(source_payload.get("name") or source_payload.get("id") or "").strip()
        source_label = f"newsapi:{source_name}" if source_name else "newsapi"
        normalized = normalize_news_record(
            {
                "title": article.get("title"),
                "summary": article.get("description"),
                "description": article.get("description"),
                "content": article.get("content"),
                "published": article.get("publishedAt"),
                "link": article.get("url"),
                "language": article.get("language"),
                "source": source_name or "newsapi",
            },
            source=source_label,
        )
        if normalized is None:
            continue
        collected.append(normalized)
    return collected
