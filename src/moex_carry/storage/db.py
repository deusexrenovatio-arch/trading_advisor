from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from moex_carry.config import AppSettings, resolve_paths
from moex_carry.storage.models import Base


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    try:
        parsed = make_url(database_url)
    except Exception:
        return
    if not parsed.drivername.startswith("sqlite"):
        return
    database = parsed.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return
    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)

def _resolve_database_url(settings: AppSettings) -> str:
    database_url = str(settings.database.url)
    try:
        parsed = make_url(database_url)
    except Exception:
        return database_url
    if not parsed.drivername.startswith("sqlite"):
        return database_url
    database = parsed.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return database_url
    database_path = Path(database).expanduser()
    if database_path.is_absolute():
        return database_url
    data_dir = resolve_paths(settings).data_dir
    text = str(database_path).replace("\\", "/")
    if text.startswith("./data/"):
        resolved_path = data_dir / text[len("./data/") :]
    elif text.startswith("data/"):
        resolved_path = data_dir / text[len("data/") :]
    else:
        resolved_path = data_dir / database_path
    normalized = str(resolved_path.resolve()).replace("\\", "/")
    resolved_url = parsed.set(database=normalized)
    return resolved_url.render_as_string(hide_password=False)



def create_engine_from_settings(settings: AppSettings):
    database_url = _resolve_database_url(settings)
    _ensure_sqlite_parent_dir(database_url)
    return create_engine(database_url, echo=settings.database.echo, future=True)


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
