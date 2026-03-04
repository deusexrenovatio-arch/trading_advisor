from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from moex_carry.news_storage import parse_any_utc


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def get_state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT state_value FROM news_state WHERE state_key = ?", (key,)).fetchone()
    if row is None:
        return None
    return str(row[0])


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO news_state (state_key, state_value, updated_at_utc)
        VALUES (?, ?, ?)
        ON CONFLICT(state_key) DO UPDATE SET
            state_value = excluded.state_value,
            updated_at_utc = excluded.updated_at_utc
        """,
        (key, value, iso_utc(utc_now())),
    )
    conn.commit()


def newsapi_usage(conn: sqlite3.Connection, day_utc: str) -> tuple[int, int]:
    row = conn.execute(
        "SELECT used_live, used_backfill FROM newsapi_usage WHERE day_utc = ?",
        (day_utc,),
    ).fetchone()
    if row is None:
        return (0, 0)
    return (int(row[0] or 0), int(row[1] or 0))


def reserve_newsapi_request(
    conn: sqlite3.Connection,
    *,
    mode: str,
    daily_quota: int,
    realtime_budget: int,
    backfill_budget: int,
    emergency_buffer: int,
) -> bool:
    day_utc = utc_now().strftime("%Y-%m-%d")
    used_live, used_backfill = newsapi_usage(conn, day_utc)
    used_total = used_live + used_backfill
    max_non_emergency = max(int(daily_quota) - int(emergency_buffer), 0)
    if used_total >= max_non_emergency:
        return False
    if mode == "live" and used_live >= int(realtime_budget):
        return False
    if mode == "backfill" and used_backfill >= int(backfill_budget):
        return False

    if mode == "live":
        used_live += 1
    elif mode == "backfill":
        used_backfill += 1

    conn.execute(
        """
        INSERT INTO newsapi_usage (day_utc, used_live, used_backfill, updated_at_utc)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(day_utc) DO UPDATE SET
            used_live = excluded.used_live,
            used_backfill = excluded.used_backfill,
            updated_at_utc = excluded.updated_at_utc
        """,
        (day_utc, used_live, used_backfill, iso_utc(utc_now())),
    )
    conn.commit()
    return True


def should_poll_newsapi_live(
    conn: sqlite3.Connection,
    *,
    commodity: str,
    now_utc: datetime,
    min_interval_minutes: int,
) -> bool:
    interval = max(int(min_interval_minutes), 0)
    if interval <= 0:
        return True
    state_key = f"newsapi_live_last_utc:{commodity.upper()}"
    raw = get_state(conn, state_key)
    last_dt = parse_any_utc(raw) if raw else None
    if last_dt is not None:
        elapsed = now_utc - last_dt
        if elapsed < timedelta(minutes=interval):
            return False
    set_state(conn, state_key, iso_utc(now_utc))
    return True
