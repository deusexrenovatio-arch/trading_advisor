from __future__ import annotations

import json
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
    if "idempotency_key" not in columns:
        statements.append("ALTER TABLE signal_executions ADD COLUMN idempotency_key VARCHAR")
    if not statements:
        return
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def _extract_idempotency_key(note: object) -> str | None:
    if not isinstance(note, str) or not note.strip():
        return None
    try:
        payload = json.loads(note)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("idempotency_key")
    if raw is None:
        return None
    key = str(raw).strip()
    return key or None


def _backfill_signal_execution_idempotency(engine) -> None:
    inspector = inspect(engine)
    if "signal_executions" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("signal_executions")}
    if "idempotency_key" not in columns:
        return
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, note FROM signal_executions "
                "WHERE idempotency_key IS NULL OR trim(idempotency_key) = ''"
            )
        ).fetchall()
        for row_id, note in rows:
            key = _extract_idempotency_key(note)
            if not key:
                continue
            conn.execute(
                text("UPDATE signal_executions SET idempotency_key = :key WHERE id = :row_id"),
                {"key": key, "row_id": int(row_id)},
            )


def _deduplicate_signal_execution_idempotency(engine) -> None:
    inspector = inspect(engine)
    if "signal_executions" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("signal_executions")}
    if "idempotency_key" not in columns:
        return
    with engine.begin() as conn:
        duplicates = conn.execute(
            text(
                "SELECT stock_secid, future_secid, idempotency_key, COUNT(*) AS cnt "
                "FROM signal_executions "
                "WHERE idempotency_key IS NOT NULL AND trim(idempotency_key) <> '' "
                "GROUP BY stock_secid, future_secid, idempotency_key "
                "HAVING COUNT(*) > 1"
            )
        ).fetchall()
        for stock_secid, future_secid, idempotency_key, _ in duplicates:
            rows = conn.execute(
                text(
                    "SELECT id "
                    "FROM signal_executions "
                    "WHERE stock_secid = :stock_secid "
                    "AND future_secid = :future_secid "
                    "AND idempotency_key = :idempotency_key "
                    "ORDER BY timestamp DESC, id DESC"
                ),
                {
                    "stock_secid": str(stock_secid),
                    "future_secid": str(future_secid),
                    "idempotency_key": str(idempotency_key),
                },
            ).fetchall()
            if len(rows) <= 1:
                continue
            keep_id = int(rows[0][0])
            for row in rows[1:]:
                row_id = int(row[0])
                if row_id == keep_id:
                    continue
                conn.execute(
                    text("DELETE FROM signal_executions WHERE id = :row_id"),
                    {"row_id": row_id},
                )


def _ensure_signal_execution_idempotency_index(engine) -> None:
    inspector = inspect(engine)
    if "signal_executions" not in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_signal_executions_pair_idempotency "
                "ON signal_executions(stock_secid, future_secid, idempotency_key) "
                "WHERE idempotency_key IS NOT NULL AND trim(idempotency_key) <> ''"
            )
        )


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
    _backfill_signal_execution_idempotency(engine)
    _deduplicate_signal_execution_idempotency(engine)
    _ensure_signal_execution_idempotency_index(engine)
    _normalize_signal_execution_action_values(engine)


def _ensure_sqlite_parent_dir(url: str) -> None:
    raw = str(url or "").strip()
    prefix = "sqlite:///"
    if not raw.startswith(prefix):
        return
    path_part = raw.removeprefix(prefix).strip()
    if not path_part or path_part == ":memory:":
        return
    db_path = Path(path_part)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
