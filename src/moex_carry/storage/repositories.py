from __future__ import annotations

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
