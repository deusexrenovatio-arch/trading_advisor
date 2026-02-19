from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from moex_carry.storage import models as db

def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime_value(value: object) -> datetime | None:
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


def _to_iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_news_hash(
    *,
    source: str,
    url: str | None,
    title: str,
    published_at: datetime,
) -> str:
    raw = "|".join(
        [
            source.strip().lower(),
            (url or "").strip().lower(),
            title.strip().lower(),
            published_at.isoformat(),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _build_news_signal_link_id(
    *,
    news_id: str,
    signal_id: str | None,
    decision_id: str | None,
    link_type: str,
    window_start: datetime,
) -> str:
    raw = "|".join(
        [
            news_id.strip(),
            (signal_id or "").strip(),
            (decision_id or "").strip(),
            link_type.strip(),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"lnk-{digest}"


def _build_news_event_update_id(
    *,
    event_id: str,
    ts_update: datetime,
    source_hash: str | None,
    source_url: str | None,
) -> str:
    raw = "|".join(
        [
            event_id.strip(),
            ts_update.isoformat(),
            (source_hash or "").strip(),
            (source_url or "").strip(),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"upd-{digest}"


def _build_news_event_link_id(
    *,
    src_event_id: str,
    dst_event_id: str,
    link_type: str,
) -> str:
    raw = "|".join([src_event_id.strip(), dst_event_id.strip(), link_type.strip()])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"xlk-{digest}"


def _build_news_label_id(
    *,
    target_level: str,
    target_id: str,
    label_source: str,
    label_version: str,
    model_version: str | None,
    prompt_version: str | None,
) -> str:
    raw = "|".join(
        [
            target_level.strip(),
            target_id.strip(),
            label_source.strip(),
            label_version.strip(),
            (model_version or "").strip(),
            (prompt_version or "").strip(),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"lbl-{digest}"


def _build_news_gold_label_id(
    *,
    target_type: str,
    target_id: str,
    source: str,
    label_schema_version: str,
) -> str:
    raw = "|".join(
        [
            target_type.strip(),
            target_id.strip(),
            source.strip(),
            label_schema_version.strip(),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"gld-{digest}"


def _build_news_unmatched_gold_id(
    *,
    source: str,
    gold_id: str,
) -> str:
    raw = "|".join([source.strip(), gold_id.strip()])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"ung-{digest}"


def _build_news_llm_input_hash(
    *,
    target_level: str,
    target_id: str,
    model_id: str,
    prompt_version: str | None,
) -> str:
    raw = "|".join(
        [
            target_level.strip(),
            target_id.strip(),
            model_id.strip(),
            (prompt_version or "").strip(),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _build_news_llm_run_id(
    *,
    target_level: str,
    target_id: str,
    provider: str,
    model_id: str,
    prompt_version: str | None,
    input_hash: str,
) -> str:
    raw = "|".join(
        [
            target_level.strip(),
            target_id.strip(),
            provider.strip(),
            model_id.strip(),
            (prompt_version or "").strip(),
            input_hash.strip(),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"llm-{digest}"


def _build_news_annotation_id(
    *,
    target_level: str,
    target_id: str,
    version: str,
    author_id: str | None,
    payload: object,
) -> str:
    payload_text = str(payload)
    raw = "|".join(
        [
            target_level.strip(),
            target_id.strip(),
            version.strip(),
            (author_id or "").strip(),
            payload_text,
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"ann-{digest}"


def _news_item_to_dict(row: db.NewsItemModel) -> dict[str, object]:
    return {
        "news_id": row.news_id,
        "source": row.source,
        "url": row.url,
        "title": row.title,
        "content": row.content,
        "language": row.language,
        "published_at": row.published_at.isoformat() + "Z",
        "ingested_at": row.ingested_at.isoformat() + "Z",
        "hash": row.hash,
    }
