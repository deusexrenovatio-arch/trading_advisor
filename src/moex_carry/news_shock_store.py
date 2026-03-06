from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from moex_carry.news_storage import open_sqlite_connection, sqlite_path_from_url

_TABLE_NAME = "news_shock_rows"


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _safe_float(value: object) -> float | None:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return None
    return float(num)


def _safe_int(value: object) -> int:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return 0
    return int(num)


def _init_table(conn: Any) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
            symbol TEXT NOT NULL,
            shock_ts TEXT NOT NULL,
            bar_minutes INTEGER NOT NULL,
            prev_ts TEXT,
            prev_price REAL,
            price REAL,
            logret REAL,
            abs_move_pct REAL,
            shock_direction TEXT,
            rolling_sigma REAL,
            z_score REAL,
            broad_event_id TEXT,
            broad_event_ts TEXT,
            broad_delay_min REAL,
            broad_title TEXT,
            broad_url TEXT,
            v2_event_id TEXT,
            v2_event_ts TEXT,
            v2_delay_min REAL,
            v2_title TEXT,
            v2_url TEXT,
            selected_event_source TEXT,
            selected_event_id TEXT,
            selected_event_ts TEXT,
            selected_delay_min REAL,
            selected_match_mode TEXT,
            selected_title TEXT,
            selected_url TEXT,
            selected_cause_event TEXT,
            selected_cause_route_key TEXT,
            selected_cause_claim_status TEXT,
            selected_cause_classification TEXT,
            selected_cause_confidence REAL,
            selected_fundamental_score REAL,
            selected_direction_alignment REAL,
            selected_is_primary_cause INTEGER,
            root_link_type TEXT,
            root_primary_shock_ts TEXT,
            root_episode_event_index INTEGER,
            root_topic_id TEXT,
            label_has_any INTEGER,
            label_has_gold INTEGER,
            label_has_silver INTEGER,
            label_gold_direction TEXT,
            label_silver_direction TEXT,
            gold_direction_match REAL,
            silver_direction_match REAL,
            updated_at_utc TEXT NOT NULL,
            row_json TEXT NOT NULL,
            PRIMARY KEY (symbol, shock_ts, bar_minutes)
        )
        """
    )
    columns = {
        str(row[1]).strip().lower()
        for row in conn.execute(f"PRAGMA table_info({_TABLE_NAME})").fetchall()
    }
    migrations: tuple[tuple[str, str], ...] = (
        ("selected_cause_event", "TEXT"),
        ("selected_cause_route_key", "TEXT"),
        ("selected_cause_claim_status", "TEXT"),
        ("selected_cause_classification", "TEXT"),
        ("selected_cause_confidence", "REAL"),
        ("selected_fundamental_score", "REAL"),
        ("selected_direction_alignment", "REAL"),
        ("selected_is_primary_cause", "INTEGER"),
        ("root_link_type", "TEXT"),
        ("root_primary_shock_ts", "TEXT"),
        ("root_episode_event_index", "INTEGER"),
    )
    for column, dtype in migrations:
        if column not in columns:
            conn.execute(f"ALTER TABLE {_TABLE_NAME} ADD COLUMN {column} {dtype}")
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{_TABLE_NAME}_shock_ts
        ON {_TABLE_NAME} (shock_ts DESC)
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{_TABLE_NAME}_selected_event
        ON {_TABLE_NAME} (selected_event_id, symbol, shock_ts DESC)
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{_TABLE_NAME}_root_topic
        ON {_TABLE_NAME} (root_topic_id, symbol, shock_ts DESC)
        """
    )
    conn.commit()


def upsert_live_shock_rows(
    *,
    frame: pd.DataFrame,
    database_url: str,
    data_dir: str | Path,
) -> int:
    if frame.empty:
        return 0
    db_path = sqlite_path_from_url(database_url, data_dir=data_dir)
    conn = open_sqlite_connection(db_path, timeout_sec=15.0, write=True)
    try:
        _init_table(conn)
        rows: list[tuple[Any, ...]] = []
        for _, row in frame.iterrows():
            payload = row.to_dict()
            rows.append(
                (
                    _normalize_text(row.get("symbol")).upper(),
                    _normalize_text(row.get("shock_ts")),
                    int(_safe_int(row.get("bar_minutes")) or 0),
                    _normalize_text(row.get("prev_ts")),
                    _safe_float(row.get("prev_price")),
                    _safe_float(row.get("price")),
                    _safe_float(row.get("logret")),
                    _safe_float(row.get("abs_move_pct")),
                    _normalize_text(row.get("shock_direction")).lower(),
                    _safe_float(row.get("rolling_sigma")),
                    _safe_float(row.get("z_score")),
                    _normalize_text(row.get("broad_event_id")),
                    _normalize_text(row.get("broad_event_ts")),
                    _safe_float(row.get("broad_delay_min")),
                    _normalize_text(row.get("broad_title")),
                    _normalize_text(row.get("broad_url")),
                    _normalize_text(row.get("v2_event_id")),
                    _normalize_text(row.get("v2_event_ts")),
                    _safe_float(row.get("v2_delay_min")),
                    _normalize_text(row.get("v2_title")),
                    _normalize_text(row.get("v2_url")),
                    _normalize_text(row.get("selected_event_source")),
                    _normalize_text(row.get("selected_event_id")),
                    _normalize_text(row.get("selected_event_ts")),
                    _safe_float(row.get("selected_delay_min")),
                    _normalize_text(row.get("selected_match_mode")),
                    _normalize_text(row.get("selected_title")),
                    _normalize_text(row.get("selected_url")),
                    _normalize_text(row.get("selected_cause_event")),
                    _normalize_text(row.get("selected_cause_route_key")),
                    _normalize_text(row.get("selected_cause_claim_status")),
                    _normalize_text(row.get("selected_cause_classification")),
                    _safe_float(row.get("selected_cause_confidence")),
                    _safe_float(row.get("selected_fundamental_score")),
                    _safe_float(row.get("selected_direction_alignment")),
                    _safe_int(row.get("selected_is_primary_cause")),
                    _normalize_text(row.get("root_link_type")),
                    _normalize_text(row.get("root_primary_shock_ts")),
                    _safe_int(row.get("root_episode_event_index")),
                    _normalize_text(row.get("root_topic_id")),
                    _safe_int(row.get("label_has_any")),
                    _safe_int(row.get("label_has_gold")),
                    _safe_int(row.get("label_has_silver")),
                    _normalize_text(row.get("label_gold_direction")),
                    _normalize_text(row.get("label_silver_direction")),
                    _safe_float(row.get("gold_direction_match")),
                    _safe_float(row.get("silver_direction_match")),
                    pd.Timestamp.utcnow().isoformat().replace("+00:00", "Z"),
                    json.dumps(payload, ensure_ascii=False, default=str),
                )
            )
        conn.executemany(
            f"""
            INSERT INTO {_TABLE_NAME} (
                symbol,
                shock_ts,
                bar_minutes,
                prev_ts,
                prev_price,
                price,
                logret,
                abs_move_pct,
                shock_direction,
                rolling_sigma,
                z_score,
                broad_event_id,
                broad_event_ts,
                broad_delay_min,
                broad_title,
                broad_url,
                v2_event_id,
                v2_event_ts,
                v2_delay_min,
                v2_title,
                v2_url,
                selected_event_source,
                selected_event_id,
                selected_event_ts,
                selected_delay_min,
                selected_match_mode,
                selected_title,
                selected_url,
                selected_cause_event,
                selected_cause_route_key,
                selected_cause_claim_status,
                selected_cause_classification,
                selected_cause_confidence,
                selected_fundamental_score,
                selected_direction_alignment,
                selected_is_primary_cause,
                root_link_type,
                root_primary_shock_ts,
                root_episode_event_index,
                root_topic_id,
                label_has_any,
                label_has_gold,
                label_has_silver,
                label_gold_direction,
                label_silver_direction,
                gold_direction_match,
                silver_direction_match,
                updated_at_utc,
                row_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, shock_ts, bar_minutes) DO UPDATE SET
                prev_ts = excluded.prev_ts,
                prev_price = excluded.prev_price,
                price = excluded.price,
                logret = excluded.logret,
                abs_move_pct = excluded.abs_move_pct,
                shock_direction = excluded.shock_direction,
                rolling_sigma = excluded.rolling_sigma,
                z_score = excluded.z_score,
                broad_event_id = excluded.broad_event_id,
                broad_event_ts = excluded.broad_event_ts,
                broad_delay_min = excluded.broad_delay_min,
                broad_title = excluded.broad_title,
                broad_url = excluded.broad_url,
                v2_event_id = excluded.v2_event_id,
                v2_event_ts = excluded.v2_event_ts,
                v2_delay_min = excluded.v2_delay_min,
                v2_title = excluded.v2_title,
                v2_url = excluded.v2_url,
                selected_event_source = excluded.selected_event_source,
                selected_event_id = excluded.selected_event_id,
                selected_event_ts = excluded.selected_event_ts,
                selected_delay_min = excluded.selected_delay_min,
                selected_match_mode = excluded.selected_match_mode,
                selected_title = excluded.selected_title,
                selected_url = excluded.selected_url,
                selected_cause_event = excluded.selected_cause_event,
                selected_cause_route_key = excluded.selected_cause_route_key,
                selected_cause_claim_status = excluded.selected_cause_claim_status,
                selected_cause_classification = excluded.selected_cause_classification,
                selected_cause_confidence = excluded.selected_cause_confidence,
                selected_fundamental_score = excluded.selected_fundamental_score,
                selected_direction_alignment = excluded.selected_direction_alignment,
                selected_is_primary_cause = excluded.selected_is_primary_cause,
                root_link_type = excluded.root_link_type,
                root_primary_shock_ts = excluded.root_primary_shock_ts,
                root_episode_event_index = excluded.root_episode_event_index,
                root_topic_id = excluded.root_topic_id,
                label_has_any = excluded.label_has_any,
                label_has_gold = excluded.label_has_gold,
                label_has_silver = excluded.label_has_silver,
                label_gold_direction = excluded.label_gold_direction,
                label_silver_direction = excluded.label_silver_direction,
                gold_direction_match = excluded.gold_direction_match,
                silver_direction_match = excluded.silver_direction_match,
                updated_at_utc = excluded.updated_at_utc,
                row_json = excluded.row_json
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return int(len(rows))


def read_live_shock_rows(
    *,
    database_url: str,
    data_dir: str | Path,
    start_ts: str | None = None,
    end_ts: str | None = None,
    bar_minutes: int | None = None,
    max_rows: int = 0,
) -> pd.DataFrame:
    db_path = sqlite_path_from_url(database_url, data_dir=data_dir)
    if not db_path.exists():
        return pd.DataFrame()
    conn = open_sqlite_connection(db_path, timeout_sec=10.0, write=False)
    try:
        columns = {
            str(row[1]).strip().lower()
            for row in conn.execute(f"PRAGMA table_info({_TABLE_NAME})").fetchall()
        }
        if not columns:
            return pd.DataFrame()
        where_parts: list[str] = []
        params: list[Any] = []
        if start_ts:
            where_parts.append("shock_ts >= ?")
            params.append(str(start_ts).strip())
        if end_ts:
            where_parts.append("shock_ts <= ?")
            params.append(str(end_ts).strip())
        if bar_minutes is not None and int(bar_minutes) > 0:
            where_parts.append("bar_minutes = ?")
            params.append(int(bar_minutes))
        where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        limit_sql = "LIMIT ?" if int(max_rows) > 0 else ""
        if int(max_rows) > 0:
            params.append(int(max_rows))
        rows = conn.execute(
            f"""
            SELECT row_json
            FROM {_TABLE_NAME}
            {where_sql}
            ORDER BY shock_ts ASC
            {limit_sql}
            """,
            tuple(params),
        ).fetchall()
    finally:
        conn.close()

    payloads: list[dict[str, Any]] = []
    for (row_json,) in rows:
        raw = str(row_json or "").strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        payloads.append({str(key): value for key, value in obj.items()})
    if not payloads:
        return pd.DataFrame()
    return pd.DataFrame(payloads)
