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
        news_id = _str_or_none(row.get("news_id"))
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
    limit: int = 2000,
) -> list[dict[str, object]]:
    query = select(db.NewsImpactScoreModel)
    if news_ids:
        normalized = [str(item).strip() for item in news_ids if str(item).strip()]
        if normalized:
            query = query.where(db.NewsImpactScoreModel.news_id.in_(normalized))
    if model_id:
        query = query.where(db.NewsImpactScoreModel.model_id == model_id)
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
