from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_data_dir(data_dir: str | Path | None) -> Path:
    if data_dir is None:
        return (repo_root() / "data").resolve()
    path = Path(data_dir).expanduser()
    if not path.is_absolute():
        path = (repo_root() / path).resolve()
    return path


def resolve_data_path(raw_path: str | Path, *, data_dir: str | Path | None = None) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    base_dir = _normalize_data_dir(data_dir)
    text = str(path).replace("\\", "/")
    if text.startswith("./data/"):
        return (base_dir / text[len("./data/") :]).resolve()
    if text.startswith("data/"):
        return (base_dir / text[len("data/") :]).resolve()
    return (base_dir / path).resolve()


def sqlite_path_from_url(database_url: str, *, data_dir: str | Path | None = None) -> Path:
    normalized = str(database_url or "").strip()
    if normalized.startswith("sqlite:///"):
        raw_path = normalized[len("sqlite:///") :]
    elif normalized.startswith("sqlite://"):
        raw_path = normalized[len("sqlite://") :]
    else:
        raise ValueError(f"Only sqlite database URL is supported: {database_url}")

    raw_path = raw_path.strip()
    if raw_path in {"", ":memory:"}:
        return Path(":memory:")
    return resolve_data_path(raw_path, data_dir=data_dir)


def open_sqlite_connection(
    database_path: Path,
    *,
    timeout_sec: float = 10.0,
    write: bool,
) -> sqlite3.Connection:
    target = str(database_path)
    if target != ":memory:" and write:
        database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=max(float(timeout_sec), 0.1))
    conn.execute(f"PRAGMA busy_timeout = {int(max(float(timeout_sec), 0.1) * 1000)}")
    conn.execute("PRAGMA foreign_keys = ON")
    if write:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.Error:
            # Keep compatibility with filesystems/modes where WAL is unavailable.
            pass
    return conn


def write_csv_atomic(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp_path, index=False)
    tmp_path.replace(path)


def parse_any_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    raw = str(value).strip()
    if not raw:
        return None
    parsed = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()
