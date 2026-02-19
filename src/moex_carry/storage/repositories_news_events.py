from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from moex_carry.storage import models as db
from moex_carry.storage.repositories_helpers import (
    _build_news_label_id,
    _build_news_llm_input_hash,
    _build_news_llm_run_id,
    _float_or_none,
    _int_or_none,
    _parse_datetime_value,
    _str_or_none,
    _to_iso_z,
)

def upsert_news_events(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        event_id = _str_or_none(row.get("event_id"))
        first_published = _parse_datetime_value(
            row.get("event_first_published_at_utc") or row.get("event_first_published_at")
        )
        if event_id is None or first_published is None:
            continue
        session.merge(
            db.NewsEventModel(
                event_id=event_id,
                event_first_published_at_utc=first_published,
                event_first_ingested_at_utc=_parse_datetime_value(
                    row.get("event_first_ingested_at_utc") or row.get("event_first_ingested_at")
                )
                or first_published,
                event_last_published_at_utc=_parse_datetime_value(
                    row.get("event_last_published_at_utc") or row.get("event_last_published_at")
                ),
                event_status=_str_or_none(row.get("event_status")) or "active",
                canonical_summary=_str_or_none(row.get("canonical_summary")),
                canonical_mechanism=_str_or_none(row.get("canonical_mechanism")),
                cluster_version=_str_or_none(row.get("cluster_version")) or "v1",
                created_at=_parse_datetime_value(row.get("created_at")) or now,
                updated_at=_parse_datetime_value(row.get("updated_at")) or now,
            )
        )
        stored += 1
    session.commit()
    return stored


def load_news_events(
    session: Session,
    *,
    event_ids: Iterable[str] | None = None,
    event_status: str | None = None,
    published_from: str | None = None,
    published_to: str | None = None,
    limit: int = 500,
) -> list[dict[str, object]]:
    query = select(db.NewsEventModel)
    if event_ids:
        normalized = [str(item).strip() for item in event_ids if str(item).strip()]
        if normalized:
            query = query.where(db.NewsEventModel.event_id.in_(normalized))
    if event_status:
        query = query.where(db.NewsEventModel.event_status == event_status)
    from_dt = _parse_datetime_value(published_from)
    to_dt = _parse_datetime_value(published_to)
    if from_dt is not None:
        query = query.where(db.NewsEventModel.event_first_published_at_utc >= from_dt)
    if to_dt is not None:
        query = query.where(db.NewsEventModel.event_first_published_at_utc <= to_dt)
    query = query.order_by(
        db.NewsEventModel.event_first_published_at_utc.desc(),
        db.NewsEventModel.event_id.desc(),
    )
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "event_id": row.event_id,
            "event_first_published_at_utc": _to_iso_z(row.event_first_published_at_utc),
            "event_first_ingested_at_utc": _to_iso_z(row.event_first_ingested_at_utc),
            "event_last_published_at_utc": _to_iso_z(row.event_last_published_at_utc),
            "event_status": row.event_status,
            "canonical_summary": row.canonical_summary,
            "canonical_mechanism": row.canonical_mechanism,
            "cluster_version": row.cluster_version,
            "created_at": _to_iso_z(row.created_at),
            "updated_at": _to_iso_z(row.updated_at),
        }
        for row in rows
    ]


def upsert_news_event_items(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        event_id = _str_or_none(row.get("event_id"))
        news_id = _str_or_none(row.get("news_id"))
        if event_id is None or news_id is None:
            continue
        session.merge(
            db.NewsEventItemModel(
                event_id=event_id,
                news_id=news_id,
                link_role=_str_or_none(row.get("link_role")) or "primary",
                similarity_score=_float_or_none(row.get("similarity_score")),
                added_at=_parse_datetime_value(row.get("added_at")) or now,
            )
        )
        stored += 1
    session.commit()
    return stored


def load_news_event_items(
    session: Session,
    *,
    event_ids: Iterable[str] | None = None,
    news_ids: Iterable[str] | None = None,
    limit: int = 5000,
) -> list[dict[str, object]]:
    query = select(db.NewsEventItemModel)
    if event_ids:
        normalized = [str(item).strip() for item in event_ids if str(item).strip()]
        if normalized:
            query = query.where(db.NewsEventItemModel.event_id.in_(normalized))
    if news_ids:
        normalized = [str(item).strip() for item in news_ids if str(item).strip()]
        if normalized:
            query = query.where(db.NewsEventItemModel.news_id.in_(normalized))
    query = query.order_by(db.NewsEventItemModel.added_at.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "event_id": row.event_id,
            "news_id": row.news_id,
            "link_role": row.link_role,
            "similarity_score": row.similarity_score,
            "added_at": _to_iso_z(row.added_at),
        }
        for row in rows
    ]


def upsert_news_labels(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        target_level = _str_or_none(row.get("target_level"))
        target_id = _str_or_none(row.get("target_id"))
        if target_level is None or target_id is None:
            continue
        label_source = _str_or_none(row.get("label_source")) or "rules"
        label_version = _str_or_none(row.get("label_version")) or "v1"
        model_version = _str_or_none(row.get("model_version"))
        prompt_version = _str_or_none(row.get("prompt_version"))
        label_id = _str_or_none(row.get("label_id")) or _build_news_label_id(
            target_level=target_level,
            target_id=target_id,
            label_source=label_source,
            label_version=label_version,
            model_version=model_version,
            prompt_version=prompt_version,
        )
        session.merge(
            db.NewsLabelModel(
                label_id=label_id,
                target_level=target_level,
                target_id=target_id,
                commodity_json=row.get("commodity_json"),
                market_scope=_str_or_none(row.get("market_scope")),
                instrument_candidates_json=row.get("instrument_candidates_json"),
                relevance=_float_or_none(row.get("relevance")),
                news_type_json=row.get("news_type_json"),
                direction=_str_or_none(row.get("direction")),
                magnitude=_float_or_none(row.get("magnitude")),
                lag_bucket=_str_or_none(row.get("lag_bucket")),
                confidence=_float_or_none(row.get("confidence")),
                uncertainty_type=_str_or_none(row.get("uncertainty_type")),
                geo_scope=_str_or_none(row.get("geo_scope")),
                evidence_json=row.get("evidence_json"),
                label_source=label_source,
                label_version=label_version,
                model_version=model_version,
                prompt_version=prompt_version,
                created_at=_parse_datetime_value(row.get("created_at")) or now,
            )
        )
        stored += 1
    session.commit()
    return stored


def load_news_labels(
    session: Session,
    *,
    target_level: str | None = None,
    target_ids: Iterable[str] | None = None,
    label_source: str | None = None,
    limit: int = 5000,
) -> list[dict[str, object]]:
    query = select(db.NewsLabelModel)
    if target_level:
        query = query.where(db.NewsLabelModel.target_level == target_level)
    if target_ids:
        normalized = [str(item).strip() for item in target_ids if str(item).strip()]
        if normalized:
            query = query.where(db.NewsLabelModel.target_id.in_(normalized))
    if label_source:
        query = query.where(db.NewsLabelModel.label_source == label_source)
    query = query.order_by(db.NewsLabelModel.created_at.desc(), db.NewsLabelModel.label_id.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "label_id": row.label_id,
            "target_level": row.target_level,
            "target_id": row.target_id,
            "commodity_json": row.commodity_json,
            "market_scope": row.market_scope,
            "instrument_candidates_json": row.instrument_candidates_json,
            "relevance": row.relevance,
            "news_type_json": row.news_type_json,
            "direction": row.direction,
            "magnitude": row.magnitude,
            "lag_bucket": row.lag_bucket,
            "confidence": row.confidence,
            "uncertainty_type": row.uncertainty_type,
            "geo_scope": row.geo_scope,
            "evidence_json": row.evidence_json,
            "label_source": row.label_source,
            "label_version": row.label_version,
            "model_version": row.model_version,
            "prompt_version": row.prompt_version,
            "created_at": _to_iso_z(row.created_at),
        }
        for row in rows
    ]


def upsert_news_llm_runs(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        target_level = _str_or_none(row.get("target_level"))
        target_id = _str_or_none(row.get("target_id"))
        model_id = _str_or_none(row.get("model_id"))
        if target_level is None or target_id is None or model_id is None:
            continue
        provider = _str_or_none(row.get("provider")) or "openai"
        prompt_version = _str_or_none(row.get("prompt_version"))
        input_hash = _str_or_none(row.get("input_hash")) or _build_news_llm_input_hash(
            target_level=target_level,
            target_id=target_id,
            model_id=model_id,
            prompt_version=prompt_version,
        )
        run_id = _str_or_none(row.get("run_id")) or _build_news_llm_run_id(
            target_level=target_level,
            target_id=target_id,
            provider=provider,
            model_id=model_id,
            prompt_version=prompt_version,
            input_hash=input_hash,
        )
        session.merge(
            db.NewsLlmRunModel(
                run_id=run_id,
                target_level=target_level,
                target_id=target_id,
                provider=provider,
                model_id=model_id,
                prompt_version=prompt_version,
                input_hash=input_hash,
                status=_str_or_none(row.get("status")) or "queued",
                token_in=int(row.get("token_in") or 0),
                token_out=int(row.get("token_out") or 0),
                latency_ms=_int_or_none(row.get("latency_ms")),
                error_code=_str_or_none(row.get("error_code")),
                created_at=_parse_datetime_value(row.get("created_at")) or now,
            )
        )
        stored += 1
    session.commit()
    return stored


def load_news_llm_runs(
    session: Session,
    *,
    target_level: str | None = None,
    target_id: str | None = None,
    status: str | None = None,
    limit: int = 1000,
) -> list[dict[str, object]]:
    query = select(db.NewsLlmRunModel)
    if target_level:
        query = query.where(db.NewsLlmRunModel.target_level == target_level)
    if target_id:
        query = query.where(db.NewsLlmRunModel.target_id == target_id)
    if status:
        query = query.where(db.NewsLlmRunModel.status == status)
    query = query.order_by(db.NewsLlmRunModel.created_at.desc(), db.NewsLlmRunModel.run_id.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "run_id": row.run_id,
            "target_level": row.target_level,
            "target_id": row.target_id,
            "provider": row.provider,
            "model_id": row.model_id,
            "prompt_version": row.prompt_version,
            "input_hash": row.input_hash,
            "status": row.status,
            "token_in": row.token_in,
            "token_out": row.token_out,
            "latency_ms": row.latency_ms,
            "error_code": row.error_code,
            "created_at": _to_iso_z(row.created_at),
        }
        for row in rows
    ]
