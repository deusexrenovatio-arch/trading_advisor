from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Iterable


def _safe_import(name: str):
    try:
        module = __import__(name, fromlist=["*"])
        return module
    except Exception:
        return None


def normalize_article_text(raw_text: str | None) -> str:
    text = str(raw_text or "")
    if not text:
        return ""
    trafilatura = _safe_import("trafilatura")
    if trafilatura is not None:
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
