from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from moex_carry.config import TelegramConfig
from moex_carry.news_storage import open_sqlite_connection, sqlite_path_from_url
from moex_carry.signals_delivery import parse_iso_utc as parse_iso


def _parse_iso_utc(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = pd.to_datetime(raw, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _to_float(value: object, *, default: float = 0.0) -> float:
    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return float(default)
    return float(parsed)


def _fmt_msk(ts: datetime) -> str:
    msk = ts.astimezone(timezone(timedelta(hours=3)))
    return msk.strftime("%d.%m.%Y %H:%M MSK")


def _format_age(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes}\u043c"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}\u0447 {minutes % 60}\u043c"
    days = hours // 24
    return f"{days}\u0434 {hours % 24}\u0447"


def _direction_label(value: object) -> str:
    direction_raw = _normalize_text(value).lower()
    if direction_raw in {"up", "long", "bullish", "increase"}:
        return "\u0440\u043e\u0441\u0442"
    if direction_raw in {"down", "short", "bearish", "decrease"}:
        return "\u043f\u0430\u0434\u0435\u043d\u0438\u0435"
    return "\u043d/\u0434"


def derive_root_fingerprint(row: dict[str, Any]) -> str:
    payload = "|".join(
        [
            _normalize_text(row.get("root_topic_id")),
            _normalize_text(row.get("symbol")).upper(),
            _normalize_text(row.get("first_shock_ts")),
            _normalize_text(row.get("selected_event_id")),
            _normalize_text(row.get("selected_title")),
        ]
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"root:{digest}"


def load_root_rows_from_db(
    *,
    database_url: str,
    data_dir: str | Path,
    since_ts: datetime | None = None,
    max_rows: int = 1000,
    min_primary_count: int = 1,
) -> list[dict[str, Any]]:
    db_path = sqlite_path_from_url(database_url, data_dir=data_dir)
    if not db_path.exists():
        return []

    conn: sqlite3.Connection | None = None
    try:
        conn = open_sqlite_connection(db_path, timeout_sec=5.0, write=False)
        columns = {
            str(row[1]).strip().lower()
            for row in conn.execute("PRAGMA table_info(news_root_registry)").fetchall()
        }
        if not columns:
            return []

        params: list[Any] = []
        where_parts: list[str] = []
        if since_ts is not None:
            where_parts.append("reg.first_shock_ts >= ?")
            params.append(_iso_utc(since_ts))
        if int(min_primary_count) > 0:
            where_parts.append("COALESCE(reg.primary_count, 0) >= ?")
            params.append(int(min_primary_count))
        where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        limit_sql = "LIMIT ?" if max_rows > 0 else ""
        if max_rows > 0:
            params.append(int(max_rows) * 2)

        rows = conn.execute(
            f"""
            SELECT
                reg.root_topic_id,
                reg.symbol,
                reg.first_shock_ts,
                reg.last_shock_ts,
                reg.shock_count,
                reg.primary_count,
                reg.aftershock_count,
                reg.max_abs_z,
                reg.avg_abs_move_pct,
                reg.last_cause_event,
                reg.last_cause_route_key,
                shock.shock_direction,
                shock.selected_event_source,
                shock.selected_event_id,
                shock.selected_event_ts,
                shock.selected_title,
                shock.selected_url,
                shock.selected_cause_event,
                shock.selected_cause_route_key,
                shock.selected_cause_claim_status,
                shock.selected_cause_classification,
                shock.selected_cause_confidence,
                shock.selected_fundamental_score,
                shock.abs_move_pct AS primary_abs_move_pct,
                shock.z_score AS primary_z_score
            FROM news_root_registry reg
            LEFT JOIN news_shock_rows shock
              ON shock.root_topic_id = reg.root_topic_id
             AND shock.symbol = reg.symbol
             AND shock.shock_ts = reg.first_shock_ts
            {where_sql}
            ORDER BY reg.first_shock_ts ASC, reg.root_topic_id ASC, reg.symbol ASC
            {limit_sql}
            """,
            tuple(params),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        if conn is not None:
            conn.close()

    if not rows:
        return []

    frame = pd.DataFrame(
        rows,
        columns=[
            "root_topic_id",
            "symbol",
            "first_shock_ts",
            "last_shock_ts",
            "shock_count",
            "primary_count",
            "aftershock_count",
            "max_abs_z",
            "avg_abs_move_pct",
            "last_cause_event",
            "last_cause_route_key",
            "shock_direction",
            "selected_event_source",
            "selected_event_id",
            "selected_event_ts",
            "selected_title",
            "selected_url",
            "selected_cause_event",
            "selected_cause_route_key",
            "selected_cause_claim_status",
            "selected_cause_classification",
            "selected_cause_confidence",
            "selected_fundamental_score",
            "primary_abs_move_pct",
            "primary_z_score",
        ],
    )
    if frame.empty:
        return []

    frame["_first_shock_dt"] = pd.to_datetime(frame["first_shock_ts"], utc=True, errors="coerce")
    frame["_last_shock_dt"] = pd.to_datetime(frame["last_shock_ts"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["_first_shock_dt"]).sort_values(
        ["_first_shock_dt", "root_topic_id", "symbol"],
        ascending=[True, True, True],
    )
    if since_ts is not None:
        frame = frame[frame["_first_shock_dt"] >= since_ts]
    if int(min_primary_count) > 0 and "primary_count" in frame.columns:
        frame = frame[pd.to_numeric(frame["primary_count"], errors="coerce").fillna(0) >= int(min_primary_count)]
    if frame.empty:
        return []
    if max_rows > 0 and len(frame) > max_rows:
        frame = frame.tail(max_rows)

    rows_out: list[dict[str, Any]] = []
    for _, item in frame.iterrows():
        row = {str(key): item[key] for key in frame.columns if not str(key).startswith("_")}
        row["first_shock_ts"] = _iso_utc(item["_first_shock_dt"].to_pydatetime())
        last_dt = item["_last_shock_dt"]
        if pd.notna(last_dt):
            row["last_shock_ts"] = _iso_utc(last_dt.to_pydatetime())
        rows_out.append(row)
    return rows_out


def format_root_message(alert: dict[str, Any]) -> str:
    first_dt = _parse_iso_utc(alert.get("first_shock_ts"))
    last_dt = _parse_iso_utc(alert.get("last_shock_ts"))
    first_label = _fmt_msk(first_dt) if first_dt is not None else str(alert.get("first_shock_ts") or "n/a")
    last_label = _fmt_msk(last_dt) if last_dt is not None else str(alert.get("last_shock_ts") or "n/a")
    age = _format_age(last_dt - first_dt) if first_dt is not None and last_dt is not None else "\u043d/\u0434"
    topic_key = _normalize_text(alert.get("root_topic_id")) or "\u043d/\u0434"
    symbol = _normalize_text(alert.get("symbol")).upper() or "N/A"
    direction = _direction_label(alert.get("shock_direction"))
    shock_count = int(pd.to_numeric(alert.get("shock_count"), errors="coerce") or 0)
    primary_count = int(pd.to_numeric(alert.get("primary_count"), errors="coerce") or 0)
    aftershock_count = int(pd.to_numeric(alert.get("aftershock_count"), errors="coerce") or 0)
    max_abs_z = _to_float(alert.get("max_abs_z"), default=_to_float(alert.get("primary_z_score")))
    avg_abs_move_pct = _to_float(alert.get("avg_abs_move_pct"), default=_to_float(alert.get("primary_abs_move_pct")))
    headline = _normalize_text(alert.get("selected_title"))
    url = _normalize_text(alert.get("selected_url"))

    lines = [
        "\u041a\u041e\u0420\u041d\u0415\u0412\u041e\u0415 \u0421\u041e\u0411\u042b\u0422\u0418\u0415",
        f"\U0001f9e9 \u0422\u0435\u043c\u0430: {topic_key}",
        f"\U0001f4c8 \u0418\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442: {symbol}",
        f"\U0001f9ed \u041d\u0430\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435: {direction}",
        (
            f"\U0001f4ca \u0421\u0447\u0435\u0442\u0447\u0438\u043a\u0438: "
            f"\u0432\u0441\u0435\u0433\u043e={shock_count} | "
            f"\u043f\u0435\u0440\u0432\u0438\u0447\u043d\u044b\u0445={primary_count} | "
            f"\u043f\u043e\u0432\u0442\u043e\u0440\u043d\u044b\u0445={aftershock_count}"
        ),
        f"\U0001f4ca \u041c\u0430\u043a\u0441 |z|={max_abs_z:.2f} | \u0441\u0440. \u0445\u043e\u0434={avg_abs_move_pct:.3f}%",
        f"\U0001f552 \u041a\u043e\u0440\u0435\u043d\u044c: {first_label}",
        f"\U0001f552 \u0421\u0435\u0439\u0447\u0430\u0441: {last_label}",
        f"\u23f3 \u0412\u043e\u0437\u0440\u0430\u0441\u0442 \u0442\u0435\u043c\u044b: {age}",
    ]
    if headline:
        lines.append(f"\U0001f4f0 {headline}")
    if url:
        lines.append(f"\U0001f517 {url}")
    return "\n".join(lines)


def apply_root_alert_policy(
    rows: list[dict[str, Any]],
    *,
    now_utc: datetime,
    state: dict[str, Any],
    max_alerts_per_cycle: int,
    sent_fingerprint_ttl_hours: int,
) -> tuple[list[dict[str, Any]], bool]:
    sent = state.get("sent_root_fingerprints")
    if not isinstance(sent, dict):
        sent = {}
        state["sent_root_fingerprints"] = sent

    alerts: list[dict[str, Any]] = []
    processed_row_ts: list[datetime] = []
    changed = False
    for row in rows:
        first_shock_ts = _parse_iso_utc(row.get("first_shock_ts"))
        if first_shock_ts is None:
            continue
        if len(alerts) >= int(max_alerts_per_cycle):
            break
        processed_row_ts.append(first_shock_ts)
        fingerprint = derive_root_fingerprint(row)
        if fingerprint in sent:
            continue
        alert = dict(row)
        alert["fingerprint"] = fingerprint
        alerts.append(alert)
        sent[fingerprint] = _iso_utc(now_utc)
        changed = True

    if processed_row_ts:
        state["root_last_processed_ts"] = _iso_utc(max(processed_row_ts))
        changed = True

    ttl = timedelta(hours=max(int(sent_fingerprint_ttl_hours), 1))
    for key in list(sent.keys()):
        ts = _parse_iso_utc(sent.get(key))
        if ts is None or now_utc > ts + ttl:
            sent.pop(key, None)
            changed = True

    return alerts, changed


def broadcast_root_alerts(
    *,
    cfg: TelegramConfig,
    state: dict[str, object],
    registered_chats: list[int],
    send_text: Callable[[int, str], None],
    save_state: Callable[[], None],
    logger: logging.Logger,
    shock_database_url: str | None = None,
    data_dir: str | Path | None = None,
) -> None:
    if not bool(cfg.root_alerts_enabled):
        return
    if not registered_chats:
        return
    if not (isinstance(shock_database_url, str) and shock_database_url.strip()) or data_dir is None:
        logger.warning("telegram.root_alerts_enabled=true but live_db_url is empty.")
        return

    since_ts = parse_iso(state.get("root_last_processed_ts"))
    max_rows = max(int(cfg.root_max_alerts_per_cycle or 1), 1) * 10
    rows = load_root_rows_from_db(
        database_url=shock_database_url,
        data_dir=data_dir,
        since_ts=since_ts,
        max_rows=max_rows,
        min_primary_count=max(int(cfg.root_min_primary_count or 1), 0),
    )
    if not rows:
        return

    now_utc = datetime.now(timezone.utc)
    alerts, changed = apply_root_alert_policy(
        rows,
        now_utc=now_utc,
        state=state,
        max_alerts_per_cycle=max(int(cfg.root_max_alerts_per_cycle), 1),
        sent_fingerprint_ttl_hours=max(int(cfg.root_sent_fingerprint_ttl_hours), 1),
    )
    if not alerts and not changed:
        return

    sent_map = state.get("sent_root_fingerprints")
    if not isinstance(sent_map, dict):
        sent_map = {}
        state["sent_root_fingerprints"] = sent_map
        changed = True

    for alert in alerts:
        message = format_root_message(alert)
        delivered = False
        for chat_id in registered_chats:
            try:
                send_text(chat_id, message)
            except Exception:
                logger.exception("Failed to send root alert to chat_id=%s", chat_id)
                continue
            delivered = True

        if not delivered:
            fingerprint = str(alert.get("fingerprint") or "").strip()
            if fingerprint and fingerprint in sent_map:
                sent_map.pop(fingerprint, None)
                changed = True

    if changed:
        save_state()
