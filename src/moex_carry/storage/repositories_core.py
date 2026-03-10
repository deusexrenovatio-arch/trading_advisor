from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from moex_carry.domain import models as domain
from moex_carry.storage import models as db
from moex_carry.storage.repositories_helpers import _parse_datetime_value, _str_or_none

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
        raw_metrics = record.get("signal_metrics")
        metrics = dict(raw_metrics) if isinstance(raw_metrics, dict) else {}
        for key in (
            "strategy_id",
            "strategy_type",
            "strategy_stream",
            "spread_mid",
            "spread_pct",
            "spot_mid",
            "future_mid",
            "price_now",
            "execution_price_now",
            "current_execution_price",
        ):
            if key not in metrics and record.get(key) is not None:
                metrics[key] = record.get(key)
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
                metrics=metrics,
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
            idempotency_key=payload.get("idempotency_key"),
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


def load_signal_execution_by_idempotency(
    session: Session,
    *,
    stock: str,
    future: str,
    idempotency_key: str,
):
    normalized_key = str(idempotency_key or "").strip()
    if not normalized_key:
        return None
    query = (
        select(db.SignalExecutionModel)
        .where(db.SignalExecutionModel.stock_secid == stock)
        .where(db.SignalExecutionModel.future_secid == future)
        .where(db.SignalExecutionModel.idempotency_key == normalized_key)
        .order_by(db.SignalExecutionModel.timestamp.desc())
        .limit(1)
    )
    return session.execute(query).scalars().first()


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
