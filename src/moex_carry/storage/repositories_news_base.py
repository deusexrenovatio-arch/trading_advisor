from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from moex_carry.storage import models as db
from moex_carry.storage.repositories_helpers import (
    _build_news_hash,
    _build_news_signal_link_id,
    _news_item_to_dict,
    _parse_datetime_value,
    _str_or_none,
)

def upsert_news_items(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        source = _str_or_none(row.get("source"))
        title = _str_or_none(row.get("title"))
        published_at = _parse_datetime_value(row.get("published_at"))
        if source is None or title is None or published_at is None:
            continue
        content = _str_or_none(row.get("content"))
        url = _str_or_none(row.get("url"))
        language = _str_or_none(row.get("language"))
        ingested_at = _parse_datetime_value(row.get("ingested_at")) or now
        hash_value = _str_or_none(row.get("hash")) or _build_news_hash(
            source=source,
            url=url,
            title=title,
            published_at=published_at,
        )
        news_id = _str_or_none(row.get("news_id")) or f"news-{hash_value[:20]}"
        existing = None
        if url is not None:
            existing = (
                session.execute(
                    select(db.NewsItemModel).where(db.NewsItemModel.url == url).limit(1)
                )
                .scalars()
                .first()
            )
        if existing is None and hash_value is not None:
            existing = (
                session.execute(
                    select(db.NewsItemModel).where(db.NewsItemModel.hash == hash_value).limit(1)
                )
                .scalars()
                .first()
            )
        if existing is not None and existing.news_id != news_id:
            if content and (existing.content is None or len(content) > len(existing.content)):
                existing.content = content
            if language and not existing.language:
                existing.language = language
            if existing.url is None and url is not None:
                existing.url = url
            if ingested_at and (existing.ingested_at is None or ingested_at > existing.ingested_at):
                existing.ingested_at = ingested_at
            if published_at and published_at < existing.published_at:
                existing.published_at = published_at
            stored += 1
            continue
        session.merge(
            db.NewsItemModel(
                news_id=news_id,
                source=source,
                url=url,
                title=title,
                content=content,
                language=language,
                published_at=published_at,
                ingested_at=ingested_at,
                hash=hash_value,
            )
        )
        stored += 1
    session.commit()
    return stored


def load_news_items(
    session: Session,
    *,
    limit: int = 200,
    published_from: str | None = None,
    published_to: str | None = None,
    source: str | None = None,
) -> list[dict[str, object]]:
    query = select(db.NewsItemModel)
    if source:
        query = query.where(db.NewsItemModel.source == source)
    from_dt = _parse_datetime_value(published_from)
    to_dt = _parse_datetime_value(published_to)
    if from_dt is not None:
        query = query.where(db.NewsItemModel.published_at >= from_dt)
    if to_dt is not None:
        query = query.where(db.NewsItemModel.published_at <= to_dt)
    query = query.order_by(db.NewsItemModel.published_at.desc(), db.NewsItemModel.news_id.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [_news_item_to_dict(row) for row in rows]


def load_news_items_by_ids(session: Session, news_ids: Iterable[str]) -> list[dict[str, object]]:
    normalized = [str(item).strip() for item in news_ids if str(item).strip()]
    if not normalized:
        return []
    query = (
        select(db.NewsItemModel)
        .where(db.NewsItemModel.news_id.in_(normalized))
        .order_by(db.NewsItemModel.published_at.desc(), db.NewsItemModel.news_id.desc())
    )
    rows = session.execute(query).scalars().all()
    return [_news_item_to_dict(row) for row in rows]


def upsert_news_entity_links(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    for row in rows:
        news_id = _str_or_none(row.get("news_id"))
        entity_type = _str_or_none(row.get("entity_type"))
        entity_id = _str_or_none(row.get("entity_id"))
        link_stage = _str_or_none(row.get("link_stage")) or "dictionary"
        if news_id is None or entity_type is None or entity_id is None:
            continue
        ticker = _str_or_none(row.get("ticker"))
        confidence = float(row.get("link_confidence") or 0.0)
        existing = (
            session.execute(
                select(db.NewsEntityLinkModel).where(
                    db.NewsEntityLinkModel.news_id == news_id,
                    db.NewsEntityLinkModel.entity_type == entity_type,
                    db.NewsEntityLinkModel.entity_id == entity_id,
                    db.NewsEntityLinkModel.ticker == ticker,
                    db.NewsEntityLinkModel.link_stage == link_stage,
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            session.add(
                db.NewsEntityLinkModel(
                    news_id=news_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    ticker=ticker,
                    link_confidence=confidence,
                    link_stage=link_stage,
                )
            )
        else:
            existing.link_confidence = confidence
        stored += 1
    session.commit()
    return stored


def load_news_entity_links(
    session: Session,
    *,
    news_ids: Iterable[str] | None = None,
    ticker: str | None = None,
    entity_id: str | None = None,
    limit: int = 1000,
) -> list[dict[str, object]]:
    query = select(db.NewsEntityLinkModel)
    if news_ids:
        normalized = [str(item).strip() for item in news_ids if str(item).strip()]
        if normalized:
            query = query.where(db.NewsEntityLinkModel.news_id.in_(normalized))
    if ticker:
        query = query.where(db.NewsEntityLinkModel.ticker == ticker)
    if entity_id:
        query = query.where(db.NewsEntityLinkModel.entity_id == entity_id)
    query = query.order_by(db.NewsEntityLinkModel.news_id.desc(), db.NewsEntityLinkModel.id.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "news_id": row.news_id,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "ticker": row.ticker,
            "link_confidence": row.link_confidence,
            "link_stage": row.link_stage,
        }
        for row in rows
    ]


def upsert_news_tags(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    for row in rows:
        tag_code = _str_or_none(row.get("tag_code"))
        tag_name = _str_or_none(row.get("tag_name"))
        if tag_code is None or tag_name is None:
            continue
        session.merge(
            db.NewsTagModel(
                tag_code=tag_code,
                tag_name=tag_name,
                description=_str_or_none(row.get("description")),
            )
        )
        stored += 1
    session.commit()
    return stored


def load_news_tags(session: Session) -> list[dict[str, object]]:
    rows = session.execute(select(db.NewsTagModel).order_by(db.NewsTagModel.tag_code)).scalars().all()
    return [
        {
            "tag_code": row.tag_code,
            "tag_name": row.tag_name,
            "description": row.description,
        }
        for row in rows
    ]


def upsert_news_item_tags(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    for row in rows:
        news_id = _str_or_none(row.get("news_id"))
        tag_code = _str_or_none(row.get("tag_code"))
        if news_id is None or tag_code is None:
            continue
        score = float(row.get("score") or 0.0)
        session.merge(
            db.NewsItemTagModel(
                news_id=news_id,
                tag_code=tag_code,
                score=score,
            )
        )
        stored += 1
    session.commit()
    return stored


def load_news_item_tags(
    session: Session,
    *,
    news_ids: Iterable[str] | None = None,
    limit: int = 1000,
) -> list[dict[str, object]]:
    query = select(db.NewsItemTagModel)
    if news_ids:
        normalized = [str(item).strip() for item in news_ids if str(item).strip()]
        if normalized:
            query = query.where(db.NewsItemTagModel.news_id.in_(normalized))
    query = query.order_by(db.NewsItemTagModel.news_id.desc(), db.NewsItemTagModel.tag_code.asc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "news_id": row.news_id,
            "tag_code": row.tag_code,
            "score": row.score,
        }
        for row in rows
    ]


def upsert_news_impact_scores(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        target_level = _str_or_none(row.get("target_level"))
        target_id = _str_or_none(row.get("target_id"))
        news_id = _str_or_none(row.get("news_id")) or (target_id if target_level and target_id else None)
        model_id = _str_or_none(row.get("model_id"))
        model_version = _str_or_none(row.get("model_version")) or "unknown"
        direction = _str_or_none(row.get("direction")) or "neutral"
        if news_id is None or model_id is None:
            continue
        prob_up = float(row.get("prob_up") or 0.0)
        prob_down = float(row.get("prob_down") or 0.0)
        prob_neutral = float(row.get("prob_neutral") or 0.0)
        impact_score = float(row.get("impact_score") or 0.0)
        calibrated = bool(row.get("calibrated"))
        inference_ts = _parse_datetime_value(row.get("inference_ts")) or now
        existing = None
        if target_level is not None and target_id is not None:
            existing = (
                session.execute(
                    select(db.NewsImpactScoreModel).where(
                        db.NewsImpactScoreModel.model_id == model_id,
                        db.NewsImpactScoreModel.model_version == model_version,
                        db.NewsImpactScoreModel.target_level == target_level,
                        db.NewsImpactScoreModel.target_id == target_id,
                    )
                )
                .scalars()
                .first()
            )
        if existing is None:
            existing = (
                session.execute(
                    select(db.NewsImpactScoreModel).where(
                        db.NewsImpactScoreModel.news_id == news_id,
                        db.NewsImpactScoreModel.model_id == model_id,
                        db.NewsImpactScoreModel.model_version == model_version,
                    )
                )
                .scalars()
                .first()
            )
        if existing is None:
            session.add(
                db.NewsImpactScoreModel(
                    news_id=news_id,
                    target_level=target_level,
                    target_id=target_id,
                    model_id=model_id,
                    model_version=model_version,
                    direction=direction,
                    prob_up=prob_up,
                    prob_down=prob_down,
                    prob_neutral=prob_neutral,
                    impact_score=impact_score,
                    calibrated=calibrated,
                    inference_ts=inference_ts,
                )
            )
        else:
            existing.news_id = news_id
            existing.target_level = target_level
            existing.target_id = target_id
            existing.direction = direction
            existing.prob_up = prob_up
            existing.prob_down = prob_down
            existing.prob_neutral = prob_neutral
            existing.impact_score = impact_score
            existing.calibrated = calibrated
            existing.inference_ts = inference_ts
        stored += 1
    session.commit()
    return stored


def load_news_impact_scores(
    session: Session,
    *,
    news_ids: Iterable[str] | None = None,
    model_id: str | None = None,
    target_level: str | None = None,
    target_ids: Iterable[str] | None = None,
    limit: int = 2000,
) -> list[dict[str, object]]:
    query = select(db.NewsImpactScoreModel)
    if news_ids:
        normalized = [str(item).strip() for item in news_ids if str(item).strip()]
        if normalized:
            query = query.where(db.NewsImpactScoreModel.news_id.in_(normalized))
    if model_id:
        query = query.where(db.NewsImpactScoreModel.model_id == model_id)
    if target_level:
        query = query.where(db.NewsImpactScoreModel.target_level == target_level)
    if target_ids:
        normalized_target = [str(item).strip() for item in target_ids if str(item).strip()]
        if normalized_target:
            query = query.where(db.NewsImpactScoreModel.target_id.in_(normalized_target))
    query = query.order_by(
        db.NewsImpactScoreModel.inference_ts.desc(),
        db.NewsImpactScoreModel.news_id.desc(),
    )
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "news_id": row.news_id,
            "target_level": row.target_level,
            "target_id": row.target_id,
            "model_id": row.model_id,
            "model_version": row.model_version,
            "direction": row.direction,
            "prob_up": row.prob_up,
            "prob_down": row.prob_down,
            "prob_neutral": row.prob_neutral,
            "impact_score": row.impact_score,
            "calibrated": bool(row.calibrated),
            "inference_ts": row.inference_ts.isoformat() + "Z",
        }
        for row in rows
    ]


def load_primary_news_scores(
    session: Session,
    *,
    news_ids: Iterable[str],
    preferred_models: Iterable[str],
) -> dict[str, dict[str, object]]:
    normalized_news_ids = [str(item).strip() for item in news_ids if str(item).strip()]
    if not normalized_news_ids:
        return {}
    scores = load_news_impact_scores(session, news_ids=normalized_news_ids, limit=20_000)
    model_priority = [str(item).strip() for item in preferred_models if str(item).strip()]
    by_news: dict[str, list[dict[str, object]]] = {}
    for score in scores:
        key = str(score.get("news_id") or "")
        if not key:
            continue
        by_news.setdefault(key, []).append(score)
    selected: dict[str, dict[str, object]] = {}
    for news_id in normalized_news_ids:
        candidates = by_news.get(news_id, [])
        if not candidates:
            continue
        chosen: dict[str, object] | None = None
        for model_name in model_priority:
            chosen = next((item for item in candidates if item.get("model_id") == model_name), None)
            if chosen is not None:
                break
        if chosen is None:
            chosen = candidates[0]
        selected[news_id] = chosen
    return selected


def upsert_news_signal_links(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        news_id = _str_or_none(row.get("news_id"))
        link_type = _str_or_none(row.get("link_type")) or "used_in_decision"
        if news_id is None:
            continue
        signal_id = _str_or_none(row.get("signal_id"))
        decision_id = _str_or_none(row.get("decision_id"))
        event_id = _str_or_none(row.get("event_id"))
        window_start = _parse_datetime_value(row.get("window_start")) or now
        window_end = _parse_datetime_value(row.get("window_end")) or now
        gate_action = _str_or_none(row.get("gate_action")) or "allow"
        source = _str_or_none(row.get("source")) or "runtime"
        link_id = _str_or_none(row.get("link_id")) or _build_news_signal_link_id(
            news_id=news_id,
            signal_id=signal_id,
            decision_id=decision_id,
            link_type=link_type,
            window_start=window_start,
        )
        session.merge(
            db.NewsSignalLinkModel(
                link_id=link_id,
                news_id=news_id,
                event_id=event_id,
                signal_id=signal_id,
                decision_id=decision_id,
                link_type=link_type,
                window_start=window_start,
                window_end=window_end,
                gate_action=gate_action,
                source=source,
                created_at=_parse_datetime_value(row.get("created_at")) or now,
            )
        )
        stored += 1
    session.commit()
    return stored


def load_news_signal_links(
    session: Session,
    *,
    signal_ids: Iterable[str] | None = None,
    news_ids: Iterable[str] | None = None,
    event_ids: Iterable[str] | None = None,
    decision_id: str | None = None,
    limit: int = 2000,
) -> list[dict[str, object]]:
    query = select(db.NewsSignalLinkModel)
    if signal_ids:
        normalized = [str(item).strip() for item in signal_ids if str(item).strip()]
        if normalized:
            query = query.where(db.NewsSignalLinkModel.signal_id.in_(normalized))
    if news_ids:
        normalized = [str(item).strip() for item in news_ids if str(item).strip()]
        if normalized:
            query = query.where(db.NewsSignalLinkModel.news_id.in_(normalized))
    if event_ids:
        normalized = [str(item).strip() for item in event_ids if str(item).strip()]
        if normalized:
            query = query.where(db.NewsSignalLinkModel.event_id.in_(normalized))
    if decision_id:
        query = query.where(db.NewsSignalLinkModel.decision_id == decision_id)
    query = query.order_by(db.NewsSignalLinkModel.created_at.desc(), db.NewsSignalLinkModel.link_id.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "link_id": row.link_id,
            "news_id": row.news_id,
            "event_id": row.event_id,
            "signal_id": row.signal_id,
            "decision_id": row.decision_id,
            "link_type": row.link_type,
            "window_start": row.window_start.isoformat() + "Z",
            "window_end": row.window_end.isoformat() + "Z",
            "gate_action": row.gate_action,
            "source": row.source,
            "created_at": row.created_at.isoformat() + "Z",
        }
        for row in rows
    ]


def upsert_news_backtest_report(session: Session, row: dict[str, object]) -> str | None:
    run_id = _str_or_none(row.get("run_id"))
    if run_id is None:
        return None
    period_from = _parse_datetime_value(row.get("period_from"))
    period_to = _parse_datetime_value(row.get("period_to"))
    horizon = _str_or_none(row.get("horizon"))
    model_id = _str_or_none(row.get("model_id"))
    metrics_json = row.get("metrics_json")
    if period_from is None or period_to is None or horizon is None or model_id is None:
        return None
    if not isinstance(metrics_json, dict):
        metrics_json = {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session.merge(
        db.NewsBacktestReportModel(
            run_id=run_id,
            period_from=period_from,
            period_to=period_to,
            horizon=horizon,
            model_id=model_id,
            metrics_json=metrics_json,
            created_at=_parse_datetime_value(row.get("created_at")) or now,
        )
    )
    session.commit()
    return run_id


def load_news_backtest_reports(
    session: Session,
    *,
    model_id: str | None = None,
    horizon: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    query = select(db.NewsBacktestReportModel)
    if model_id:
        query = query.where(db.NewsBacktestReportModel.model_id == model_id)
    if horizon:
        query = query.where(db.NewsBacktestReportModel.horizon == horizon)
    query = query.order_by(db.NewsBacktestReportModel.created_at.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "run_id": row.run_id,
            "period_from": row.period_from.isoformat() + "Z",
            "period_to": row.period_to.isoformat() + "Z",
            "horizon": row.horizon,
            "model_id": row.model_id,
            "metrics_json": row.metrics_json,
            "created_at": row.created_at.isoformat() + "Z",
        }
        for row in rows
    ]
