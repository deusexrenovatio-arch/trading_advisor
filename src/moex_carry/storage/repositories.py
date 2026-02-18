from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from moex_carry.domain import models as domain
from moex_carry.storage import models as db


def upsert_instruments(session: Session, instruments: Iterable[domain.Instrument]) -> None:
    for instrument in instruments:
        session.merge(
            db.InstrumentModel(
                secid=instrument.secid,
                name=instrument.name,
                instrument_type=instrument.instrument_type,
                currency=instrument.currency,
                board=instrument.board,
            )
        )
    session.commit()


def upsert_contract_specs(session: Session, specs: Iterable[domain.ContractSpec]) -> None:
    for spec in specs:
        session.merge(
            db.ContractSpecModel(
                secid=spec.secid,
                asset_code=spec.asset_code,
                expiry=spec.expiry,
                lot_size=spec.lot_size,
                price_step=spec.price_step,
                multiplier=spec.multiplier,
            )
        )
    session.commit()


def store_dividends(session: Session, events: Iterable[domain.DividendEvent]) -> None:
    for event in events:
        session.add(
            db.DividendEventModel(
                secid=event.secid,
                ex_date=event.ex_date,
                amount=event.amount,
                currency=event.currency,
                status=event.status,
            )
        )
    session.commit()


def store_key_rates(session: Session, rates: Iterable[domain.KeyRate]) -> None:
    for rate in rates:
        session.merge(db.KeyRateModel(date=rate.date, rate=rate.rate))
    session.commit()


def load_instruments(session: Session) -> list[domain.Instrument]:
    rows = session.execute(select(db.InstrumentModel)).scalars().all()
    return [
        domain.Instrument(
            secid=row.secid,
            name=row.name,
            instrument_type=row.instrument_type,
            currency=row.currency,
            board=row.board,
        )
        for row in rows
    ]


def load_contract_specs(session: Session) -> list[domain.ContractSpec]:
    rows = session.execute(select(db.ContractSpecModel)).scalars().all()
    return [
        domain.ContractSpec(
            secid=row.secid,
            asset_code=row.asset_code,
            expiry=row.expiry,
            lot_size=row.lot_size,
            price_step=row.price_step,
            multiplier=row.multiplier,
        )
        for row in rows
    ]


def load_dividends(session: Session, secid: str) -> list[domain.DividendEvent]:
    rows = (
        session.execute(
            select(db.DividendEventModel).where(db.DividendEventModel.secid == secid)
        )
        .scalars()
        .all()
    )
    return [
        domain.DividendEvent(
            secid=row.secid,
            ex_date=row.ex_date,
            amount=row.amount,
            currency=row.currency,
            status=row.status,
        )
        for row in rows
    ]


def load_key_rates(session: Session) -> list[domain.KeyRate]:
    rows = session.execute(select(db.KeyRateModel)).scalars().all()
    return [domain.KeyRate(date=row.date, rate=row.rate) for row in rows]


def store_signal_run(session: Session, run_id: str, as_of, params: dict) -> None:
    session.merge(db.SignalRunModel(run_id=run_id, as_of=as_of, params=params))
    session.commit()


def store_signal_history(
    session: Session,
    run_id: str,
    timestamp,
    records: list[dict[str, object]],
) -> None:
    for record in records:
        session.add(
            db.SignalHistoryModel(
                run_id=run_id,
                timestamp=timestamp,
                stock_secid=str(record.get("stock")),
                future_secid=str(record.get("future")),
                action=str(record.get("signal_action")),
                direction=record.get("signal_direction"),
                score=float(record.get("signal_score", 0.0)),
                reasons=record.get("signal_reasons") or [],
                metrics=record.get("signal_metrics") or {},
            )
        )
    session.commit()


def delete_signal_history_run(session: Session, run_id: str) -> None:
    session.execute(delete(db.SignalHistoryModel).where(db.SignalHistoryModel.run_id == run_id))
    session.commit()


def store_signal_execution(
    session: Session,
    timestamp,
    payload: dict[str, object],
) -> None:
    session.add(
        db.SignalExecutionModel(
            timestamp=timestamp,
            stock_secid=str(payload.get("stock")),
            future_secid=str(payload.get("future")),
            direction=payload.get("direction"),
            action=str(payload.get("action", "enter")),
            price=payload.get("price"),
            quantity=payload.get("quantity"),
            side=payload.get("side"),
            order_id=payload.get("order_id"),
            status=payload.get("status"),
            note=payload.get("note"),
        )
    )
    session.commit()


def load_latest_signal_run(session: Session):
    row = session.execute(
        select(db.SignalRunModel).order_by(db.SignalRunModel.as_of.desc()).limit(1)
    ).scalars().first()
    return row


def load_signal_history(
    session: Session,
    from_ts=None,
    to_ts=None,
    limit: int | None = None,
    stock: str | None = None,
    future: str | None = None,
    action: str | None = None,
):
    query = select(db.SignalHistoryModel)
    if stock:
        query = query.where(db.SignalHistoryModel.stock_secid == stock)
    if future:
        query = query.where(db.SignalHistoryModel.future_secid == future)
    if action:
        query = query.where(db.SignalHistoryModel.action == action)
    if from_ts is not None:
        query = query.where(db.SignalHistoryModel.timestamp >= from_ts)
    if to_ts is not None:
        query = query.where(db.SignalHistoryModel.timestamp <= to_ts)
    query = query.order_by(db.SignalHistoryModel.timestamp.desc())
    if limit is not None and limit > 0:
        query = query.limit(limit)
    return session.execute(query).scalars().all()


def load_active_signals(session: Session, run_id: str):
    rows = session.execute(
        select(db.SignalHistoryModel).where(db.SignalHistoryModel.run_id == run_id)
    ).scalars().all()
    return rows


def load_open_executions(session: Session):
    rows = session.execute(select(db.SignalExecutionModel)).scalars().all()
    return rows


def upsert_quotes(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    for row in rows:
        secid = _str_or_none(row.get("secid"))
        timestamp = _parse_datetime_value(row.get("timestamp"))
        if secid is None or timestamp is None:
            continue
        existing = (
            session.execute(
                select(db.QuoteModel).where(
                    db.QuoteModel.secid == secid,
                    db.QuoteModel.timestamp == timestamp,
                )
            )
            .scalars()
            .first()
        )
        bid = float(row.get("bid")) if row.get("bid") is not None else None
        ask = float(row.get("ask")) if row.get("ask") is not None else None
        last = float(row.get("last")) if row.get("last") is not None else None
        volume = float(row.get("volume")) if row.get("volume") is not None else None
        if existing is None:
            session.add(
                db.QuoteModel(
                    secid=secid,
                    timestamp=timestamp,
                    bid=bid,
                    ask=ask,
                    last=last,
                    volume=volume,
                )
            )
        else:
            existing.bid = bid
            existing.ask = ask
            existing.last = last
            existing.volume = volume
        stored += 1
    session.commit()
    return stored


def load_signal_executions(
    session: Session, stock: str | None = None, future: str | None = None, limit: int | None = None
):
    query = select(db.SignalExecutionModel)
    if stock:
        query = query.where(db.SignalExecutionModel.stock_secid == stock)
    if future:
        query = query.where(db.SignalExecutionModel.future_secid == future)
    query = query.order_by(db.SignalExecutionModel.timestamp.desc())
    if limit is not None and limit > 0:
        query = query.limit(limit)
    return session.execute(query).scalars().all()


def upsert_decision_view_projection(
    session: Session, rows: Iterable[dict[str, object]]
) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        decision_id = str(row.get("decision_id") or "").strip()
        if not decision_id:
            continue
        created_at = _parse_datetime_value(row.get("created_at"))
        session.merge(
            db.DecisionViewProjectionModel(
                decision_id=decision_id,
                created_at=created_at,
                strategy_type=_str_or_none(row.get("strategy_type")),
                primary_instrument=_str_or_none(row.get("primary_instrument")),
                action=_str_or_none(row.get("action")),
                risk_state=_str_or_none(row.get("risk_state")),
                news_severity=_str_or_none(row.get("news_severity")),
                payload={key: value for key, value in row.items()},
                updated_at=now,
            )
        )
        stored += 1
    session.commit()
    return stored


def load_decision_view_projection(
    session: Session,
    *,
    limit: int = 500,
    strategy_type: str | None = None,
    primary_instrument: str | None = None,
    risk_state: str | None = None,
    news_severity: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
) -> list[dict[str, object]]:
    query = select(db.DecisionViewProjectionModel)
    if strategy_type:
        query = query.where(db.DecisionViewProjectionModel.strategy_type == strategy_type)
    if primary_instrument:
        query = query.where(db.DecisionViewProjectionModel.primary_instrument == primary_instrument)
    if risk_state:
        query = query.where(db.DecisionViewProjectionModel.risk_state == risk_state)
    if news_severity:
        query = query.where(db.DecisionViewProjectionModel.news_severity == news_severity)

    from_dt = _parse_datetime_value(created_from)
    to_dt = _parse_datetime_value(created_to)
    if from_dt is not None:
        query = query.where(db.DecisionViewProjectionModel.created_at >= from_dt)
    if to_dt is not None:
        query = query.where(db.DecisionViewProjectionModel.created_at <= to_dt)

    query = query.order_by(db.DecisionViewProjectionModel.created_at.desc())
    if limit > 0:
        query = query.limit(limit)

    result: list[dict[str, object]] = []
    for row in session.execute(query).scalars().all():
        payload = row.payload if isinstance(row.payload, dict) else {}
        item: dict[str, object] = dict(payload)
        item.setdefault("decision_id", row.decision_id)
        item.setdefault("strategy_type", row.strategy_type)
        item.setdefault("primary_instrument", row.primary_instrument)
        item.setdefault("action", row.action)
        item.setdefault("risk_state", row.risk_state)
        item.setdefault("news_severity", row.news_severity)
        if row.created_at is not None and not item.get("created_at"):
            item["created_at"] = row.created_at.isoformat() + "Z"
        result.append(item)
    return result


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
