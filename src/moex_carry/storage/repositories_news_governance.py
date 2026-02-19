from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from moex_carry.storage import models as db
from moex_carry.storage.repositories_helpers import (
    _build_news_annotation_id,
    _build_news_event_link_id,
    _build_news_event_update_id,
    _build_news_gold_label_id,
    _build_news_unmatched_gold_id,
    _float_or_none,
    _parse_datetime_value,
    _str_or_none,
    _to_iso_z,
)

def upsert_event_market_reactions(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        event_id = _str_or_none(row.get("event_id"))
        instrument_id = _str_or_none(row.get("instrument_id"))
        window_id = _str_or_none(row.get("window_id"))
        sampling_freq = _str_or_none(row.get("sampling_freq")) or "5m"
        if event_id is None or instrument_id is None or window_id is None:
            continue
        existing = (
            session.execute(
                select(db.EventMarketReactionModel).where(
                    db.EventMarketReactionModel.event_id == event_id,
                    db.EventMarketReactionModel.instrument_id == instrument_id,
                    db.EventMarketReactionModel.window_id == window_id,
                    db.EventMarketReactionModel.sampling_freq == sampling_freq,
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            session.add(
                db.EventMarketReactionModel(
                    event_id=event_id,
                    instrument_id=instrument_id,
                    window_id=window_id,
                    sampling_freq=sampling_freq,
                    return_raw=_float_or_none(row.get("return_raw")),
                    return_abnormal=_float_or_none(row.get("return_abnormal")),
                    car=_float_or_none(row.get("car")),
                    rv=_float_or_none(row.get("rv")),
                    vol_change=_float_or_none(row.get("vol_change")),
                    volume_change=_float_or_none(row.get("volume_change")),
                    quality_flags_json=row.get("quality_flags_json"),
                    computed_at=_parse_datetime_value(row.get("computed_at")) or now,
                )
            )
        else:
            existing.return_raw = _float_or_none(row.get("return_raw"))
            existing.return_abnormal = _float_or_none(row.get("return_abnormal"))
            existing.car = _float_or_none(row.get("car"))
            existing.rv = _float_or_none(row.get("rv"))
            existing.vol_change = _float_or_none(row.get("vol_change"))
            existing.volume_change = _float_or_none(row.get("volume_change"))
            existing.quality_flags_json = row.get("quality_flags_json")
            existing.computed_at = _parse_datetime_value(row.get("computed_at")) or now
        stored += 1
    session.commit()
    return stored


def load_event_market_reactions(
    session: Session,
    *,
    event_ids: Iterable[str] | None = None,
    instrument_id: str | None = None,
    window_id: str | None = None,
    sampling_freq: str | None = None,
    limit: int = 5000,
) -> list[dict[str, object]]:
    query = select(db.EventMarketReactionModel)
    if event_ids:
        normalized = [str(item).strip() for item in event_ids if str(item).strip()]
        if normalized:
            query = query.where(db.EventMarketReactionModel.event_id.in_(normalized))
    if instrument_id:
        query = query.where(db.EventMarketReactionModel.instrument_id == instrument_id)
    if window_id:
        query = query.where(db.EventMarketReactionModel.window_id == window_id)
    if sampling_freq:
        query = query.where(db.EventMarketReactionModel.sampling_freq == sampling_freq)
    query = query.order_by(db.EventMarketReactionModel.computed_at.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "event_id": row.event_id,
            "instrument_id": row.instrument_id,
            "window_id": row.window_id,
            "sampling_freq": row.sampling_freq,
            "return_raw": row.return_raw,
            "return_abnormal": row.return_abnormal,
            "car": row.car,
            "rv": row.rv,
            "vol_change": row.vol_change,
            "volume_change": row.volume_change,
            "quality_flags_json": row.quality_flags_json,
            "computed_at": _to_iso_z(row.computed_at),
        }
        for row in rows
    ]


def upsert_news_annotations(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        target_level = _str_or_none(row.get("target_level"))
        target_id = _str_or_none(row.get("target_id"))
        if target_level is None or target_id is None:
            continue
        payload_json = row.get("payload_json")
        if not isinstance(payload_json, (dict, list)):
            payload_json = {}
        version = _str_or_none(row.get("version")) or "v1"
        author_id = _str_or_none(row.get("author_id"))
        reason = _str_or_none(row.get("reason"))
        annotation_id = _str_or_none(row.get("annotation_id")) or _build_news_annotation_id(
            target_level=target_level,
            target_id=target_id,
            version=version,
            author_id=author_id,
            payload=payload_json,
        )
        session.merge(
            db.NewsAnnotationModel(
                annotation_id=annotation_id,
                target_level=target_level,
                target_id=target_id,
                payload_json=payload_json,
                author_id=author_id,
                reason=reason,
                version=version,
                created_at=_parse_datetime_value(row.get("created_at")) or now,
            )
        )
        stored += 1
    session.commit()
    return stored


def load_news_annotations(
    session: Session,
    *,
    target_level: str | None = None,
    target_id: str | None = None,
    author_id: str | None = None,
    limit: int = 1000,
) -> list[dict[str, object]]:
    query = select(db.NewsAnnotationModel)
    if target_level:
        query = query.where(db.NewsAnnotationModel.target_level == target_level)
    if target_id:
        query = query.where(db.NewsAnnotationModel.target_id == target_id)
    if author_id:
        query = query.where(db.NewsAnnotationModel.author_id == author_id)
    query = query.order_by(db.NewsAnnotationModel.created_at.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "annotation_id": row.annotation_id,
            "target_level": row.target_level,
            "target_id": row.target_id,
            "payload_json": row.payload_json,
            "author_id": row.author_id,
            "reason": row.reason,
            "version": row.version,
            "created_at": _to_iso_z(row.created_at),
        }
        for row in rows
    ]


def upsert_news_event_updates(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        event_id = _str_or_none(row.get("event_id"))
        ts_update = _parse_datetime_value(row.get("ts_update"))
        if event_id is None or ts_update is None:
            continue
        source_hash = _str_or_none(row.get("source_hash"))
        source_url = _str_or_none(row.get("source_url"))
        update_id = _str_or_none(row.get("update_id")) or _build_news_event_update_id(
            event_id=event_id,
            ts_update=ts_update,
            source_hash=source_hash,
            source_url=source_url,
        )
        session.merge(
            db.NewsEventUpdateModel(
                update_id=update_id,
                event_id=event_id,
                ts_update=ts_update,
                phase=_str_or_none(row.get("phase")),
                severity=_float_or_none(row.get("severity")),
                facts_json=row.get("facts_json"),
                factor_delta_json=row.get("factor_delta_json"),
                source_url=source_url,
                source_hash=source_hash,
                created_at=_parse_datetime_value(row.get("created_at")) or now,
            )
        )
        stored += 1
    session.commit()
    return stored


def load_news_event_updates(
    session: Session,
    *,
    event_id: str | None = None,
    event_ids: Iterable[str] | None = None,
    phase: str | None = None,
    limit: int = 5000,
) -> list[dict[str, object]]:
    query = select(db.NewsEventUpdateModel)
    if event_id:
        query = query.where(db.NewsEventUpdateModel.event_id == str(event_id).strip())
    if event_ids:
        normalized = [str(item).strip() for item in event_ids if str(item).strip()]
        if normalized:
            query = query.where(db.NewsEventUpdateModel.event_id.in_(normalized))
    if phase:
        query = query.where(db.NewsEventUpdateModel.phase == str(phase).strip())
    query = query.order_by(db.NewsEventUpdateModel.ts_update.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "update_id": row.update_id,
            "event_id": row.event_id,
            "ts_update": _to_iso_z(row.ts_update),
            "phase": row.phase,
            "severity": row.severity,
            "facts_json": row.facts_json,
            "factor_delta_json": row.factor_delta_json,
            "source_url": row.source_url,
            "source_hash": row.source_hash,
            "created_at": _to_iso_z(row.created_at),
        }
        for row in rows
    ]


def upsert_news_event_links(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        src_event_id = _str_or_none(row.get("src_event_id"))
        dst_event_id = _str_or_none(row.get("dst_event_id"))
        link_type = _str_or_none(row.get("link_type"))
        if src_event_id is None or dst_event_id is None or link_type is None:
            continue
        link_id = _str_or_none(row.get("link_id")) or _build_news_event_link_id(
            src_event_id=src_event_id,
            dst_event_id=dst_event_id,
            link_type=link_type,
        )
        session.merge(
            db.NewsEventLinkModel(
                link_id=link_id,
                src_event_id=src_event_id,
                dst_event_id=dst_event_id,
                link_type=link_type,
                confidence=_float_or_none(row.get("confidence")),
                evidence_json=row.get("evidence_json"),
                created_at=_parse_datetime_value(row.get("created_at")) or now,
            )
        )
        stored += 1
    session.commit()
    return stored


def load_news_event_links(
    session: Session,
    *,
    src_event_id: str | None = None,
    dst_event_id: str | None = None,
    link_type: str | None = None,
    limit: int = 5000,
) -> list[dict[str, object]]:
    query = select(db.NewsEventLinkModel)
    if src_event_id:
        query = query.where(db.NewsEventLinkModel.src_event_id == str(src_event_id).strip())
    if dst_event_id:
        query = query.where(db.NewsEventLinkModel.dst_event_id == str(dst_event_id).strip())
    if link_type:
        query = query.where(db.NewsEventLinkModel.link_type == str(link_type).strip())
    query = query.order_by(db.NewsEventLinkModel.created_at.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "link_id": row.link_id,
            "src_event_id": row.src_event_id,
            "dst_event_id": row.dst_event_id,
            "link_type": row.link_type,
            "confidence": row.confidence,
            "evidence_json": row.evidence_json,
            "created_at": _to_iso_z(row.created_at),
        }
        for row in rows
    ]


def upsert_news_gold_labels(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        target_type = _str_or_none(row.get("target_type"))
        target_id = _str_or_none(row.get("target_id"))
        source = _str_or_none(row.get("source"))
        if target_type is None or target_id is None or source is None:
            continue
        label_schema_version = _str_or_none(row.get("label_schema_version")) or "v1"
        label_id = _str_or_none(row.get("label_id")) or _build_news_gold_label_id(
            target_type=target_type,
            target_id=target_id,
            source=source,
            label_schema_version=label_schema_version,
        )
        session.merge(
            db.NewsGoldLabelModel(
                label_id=label_id,
                target_type=target_type,
                target_id=target_id,
                event_family=_str_or_none(row.get("event_family")),
                factors_json=row.get("factors_json"),
                phase=_str_or_none(row.get("phase")),
                direction_label=_str_or_none(row.get("direction_label")),
                quality=_str_or_none(row.get("quality")) or "gold",
                source=source,
                label_schema_version=label_schema_version,
                confidence=_float_or_none(row.get("confidence")),
                meta_json=row.get("meta_json"),
                created_at=_parse_datetime_value(row.get("created_at")) or now,
            )
        )
        stored += 1
    session.commit()
    return stored


def load_news_gold_labels(
    session: Session,
    *,
    target_type: str | None = None,
    target_ids: Iterable[str] | None = None,
    source: str | None = None,
    quality: str | None = None,
    limit: int = 5000,
) -> list[dict[str, object]]:
    query = select(db.NewsGoldLabelModel)
    if target_type:
        query = query.where(db.NewsGoldLabelModel.target_type == str(target_type).strip())
    if target_ids:
        normalized = [str(item).strip() for item in target_ids if str(item).strip()]
        if normalized:
            query = query.where(db.NewsGoldLabelModel.target_id.in_(normalized))
    if source:
        query = query.where(db.NewsGoldLabelModel.source == str(source).strip())
    if quality:
        query = query.where(db.NewsGoldLabelModel.quality == str(quality).strip())
    query = query.order_by(db.NewsGoldLabelModel.created_at.desc(), db.NewsGoldLabelModel.label_id.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "label_id": row.label_id,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "event_family": row.event_family,
            "factors_json": row.factors_json,
            "phase": row.phase,
            "direction_label": row.direction_label,
            "quality": row.quality,
            "source": row.source,
            "label_schema_version": row.label_schema_version,
            "confidence": row.confidence,
            "meta_json": row.meta_json,
            "created_at": _to_iso_z(row.created_at),
        }
        for row in rows
    ]


def upsert_news_unmatched_gold(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        source = _str_or_none(row.get("source"))
        gold_id = _str_or_none(row.get("gold_id"))
        if source is None or gold_id is None:
            continue
        unmatched_id = _str_or_none(row.get("unmatched_id")) or _build_news_unmatched_gold_id(
            source=source,
            gold_id=gold_id,
        )
        session.merge(
            db.NewsUnmatchedGoldModel(
                unmatched_id=unmatched_id,
                source=source,
                gold_id=gold_id,
                published_at_utc=_parse_datetime_value(row.get("published_at_utc")),
                commodity_json=row.get("commodity_json"),
                event_family=_str_or_none(row.get("event_family")),
                confidence=_float_or_none(row.get("confidence")),
                match_score=_float_or_none(row.get("match_score")),
                reason=_str_or_none(row.get("reason")),
                payload_json=row.get("payload_json"),
                created_at=_parse_datetime_value(row.get("created_at")) or now,
            )
        )
        stored += 1
    session.commit()
    return stored


def load_news_unmatched_gold(
    session: Session,
    *,
    source: str | None = None,
    event_family: str | None = None,
    published_from: str | None = None,
    published_to: str | None = None,
    limit: int = 5000,
) -> list[dict[str, object]]:
    query = select(db.NewsUnmatchedGoldModel)
    if source:
        query = query.where(db.NewsUnmatchedGoldModel.source == str(source).strip())
    if event_family:
        query = query.where(db.NewsUnmatchedGoldModel.event_family == str(event_family).strip())
    from_ts = _parse_datetime_value(published_from)
    to_ts = _parse_datetime_value(published_to)
    if from_ts is not None:
        query = query.where(db.NewsUnmatchedGoldModel.published_at_utc >= from_ts)
    if to_ts is not None:
        query = query.where(db.NewsUnmatchedGoldModel.published_at_utc <= to_ts)
    query = query.order_by(db.NewsUnmatchedGoldModel.created_at.desc(), db.NewsUnmatchedGoldModel.unmatched_id.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "unmatched_id": row.unmatched_id,
            "source": row.source,
            "gold_id": row.gold_id,
            "published_at_utc": _to_iso_z(row.published_at_utc),
            "commodity_json": row.commodity_json,
            "event_family": row.event_family,
            "confidence": row.confidence,
            "match_score": row.match_score,
            "reason": row.reason,
            "payload_json": row.payload_json,
            "created_at": _to_iso_z(row.created_at),
        }
        for row in rows
    ]


def upsert_news_model_eval_record(session: Session, row: dict[str, object]) -> str | None:
    run_id = _str_or_none(row.get("run_id"))
    model_version = _str_or_none(row.get("model_version"))
    if run_id is None or model_version is None:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session.merge(
        db.NewsModelEvalRecordModel(
            run_id=run_id,
            model_version=model_version,
            dataset_version=_str_or_none(row.get("dataset_version")),
            horizon=_str_or_none(row.get("horizon")),
            supervised_metrics_json=row.get("supervised_metrics_json"),
            market_metrics_json=row.get("market_metrics_json"),
            pass_supervised=bool(row.get("pass_supervised")),
            pass_market=bool(row.get("pass_market")),
            promotion_state=_str_or_none(row.get("promotion_state")) or "hold",
            gate_details_json=row.get("gate_details_json"),
            created_at=_parse_datetime_value(row.get("created_at")) or now,
        )
    )
    session.commit()
    return run_id


def load_news_model_eval_records(
    session: Session,
    *,
    model_version: str | None = None,
    horizon: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    query = select(db.NewsModelEvalRecordModel)
    if model_version:
        query = query.where(db.NewsModelEvalRecordModel.model_version == str(model_version).strip())
    if horizon:
        query = query.where(db.NewsModelEvalRecordModel.horizon == str(horizon).strip())
    query = query.order_by(db.NewsModelEvalRecordModel.created_at.desc(), db.NewsModelEvalRecordModel.run_id.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "run_id": row.run_id,
            "model_version": row.model_version,
            "dataset_version": row.dataset_version,
            "horizon": row.horizon,
            "supervised_metrics_json": row.supervised_metrics_json,
            "market_metrics_json": row.market_metrics_json,
            "pass_supervised": bool(row.pass_supervised),
            "pass_market": bool(row.pass_market),
            "promotion_state": row.promotion_state,
            "gate_details_json": row.gate_details_json,
            "created_at": _to_iso_z(row.created_at),
        }
        for row in rows
    ]
