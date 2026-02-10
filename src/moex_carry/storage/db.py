from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from moex_carry.config import AppSettings
from moex_carry.storage.models import Base


def create_engine_from_settings(settings: AppSettings):
    return create_engine(settings.database.url, echo=settings.database.echo, future=True)


def create_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _ensure_signal_executions_columns(engine) -> None:
    inspector = inspect(engine)
    if "signal_executions" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("signal_executions")}
    statements: list[str] = []
    if "order_id" not in columns:
        statements.append("ALTER TABLE signal_executions ADD COLUMN order_id VARCHAR")
    if not statements:
        return
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def _normalize_signal_execution_action_values(engine) -> None:
    inspector = inspect(engine)
    if "signal_executions" not in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE signal_executions "
                "SET action = 'enter' "
                "WHERE lower(coalesce(action, '')) IN ('hold_open', 'hold', 'open')"
            )
        )


def init_db(engine) -> None:
    Base.metadata.create_all(engine)
    _ensure_signal_executions_columns(engine)
    _normalize_signal_execution_action_values(engine)
