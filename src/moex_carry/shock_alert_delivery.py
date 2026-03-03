from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


_TOPIC_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "will",
    "into",
    "over",
    "after",
    "amid",
    "news",
    "report",
    "reports",
    "update",
    "market",
    "markets",
    "prices",
    "price",
}


@dataclass(frozen=True)
class ShockAlertPolicy:
    primary_min_z: float = 2.5
    aftershock_min_z: float = 2.0
    topic_reopen_after_hours: int = 168
    aftershock_cooldown_minutes: int = 60
    max_alerts_per_cycle: int = 20
    sent_fingerprint_ttl_hours: int = 24 * 21


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


def _topic_tokens(text: str) -> list[str]:
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9]{3,}", lowered)
    return [token for token in tokens if token not in _TOPIC_STOPWORDS]


def derive_topic_key(row: dict[str, Any]) -> str:
    for key in (
        "root_topic_id",
        "topic_key",
        "theme_key",
        "root_event_id",
        "selected_event_id",
        "event_id",
    ):
        value = _normalize_text(row.get(key))
        if value:
            return value.lower()

    headline = _normalize_text(
        row.get("headline")
        or row.get("selected_title")
        or row.get("v2_title")
        or row.get("broad_title")
        or row.get("title")
    )
    if headline:
        tokens = _topic_tokens(headline)[:6]
        if tokens:
            return "topic:" + "-".join(tokens)

    symbol = _normalize_text(row.get("symbol")).upper() or "UNK"
    direction = _normalize_text(row.get("shock_direction")).lower() or "neutral"
    return f"fallback:{symbol}:{direction}"


def derive_shock_fingerprint(row: dict[str, Any]) -> str:
    for key in ("shock_id", "id", "event_uid", "uid"):
        value = _normalize_text(row.get(key))
        if value:
            return value
    payload = "|".join(
        [
            _normalize_text(row.get("symbol")).upper(),
            _normalize_text(row.get("shock_ts")),
            _normalize_text(row.get("shock_direction")).lower(),
            f"{float(pd.to_numeric(row.get('z_score'), errors='coerce') or 0.0):.4f}",
            _normalize_text(
                row.get("headline")
                or row.get("selected_title")
                or row.get("v2_title")
                or row.get("broad_title")
                or row.get("title")
            ),
        ]
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"shock:{digest}"


def load_shock_rows(
    feed_path: Path,
    *,
    since_ts: datetime | None = None,
    max_rows: int = 1000,
) -> list[dict[str, Any]]:
    if not feed_path.exists():
        return []
    df = pd.read_csv(feed_path)
    if df.empty:
        return []
    ts_col = None
    for candidate in ("shock_ts", "timestamp", "ts", "event_ts"):
        if candidate in df.columns:
            ts_col = candidate
            break
    if ts_col is None:
        return []

    df["_shock_ts_dt"] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    df = df.dropna(subset=["_shock_ts_dt"]).sort_values("_shock_ts_dt")
    if since_ts is not None:
        df = df[df["_shock_ts_dt"] > since_ts]
    if df.empty:
        return []

    if max_rows > 0 and len(df) > max_rows:
        df = df.tail(max_rows)

    rows: list[dict[str, Any]] = []
    for _, item in df.iterrows():
        row = {str(key): item[key] for key in df.columns if key != "_shock_ts_dt"}
        row["shock_ts"] = _iso_utc(item["_shock_ts_dt"].to_pydatetime())
        rows.append(row)
    return rows


def _episode_id(topic_key: str, ordinal: int) -> str:
    digest = hashlib.sha1(topic_key.encode("utf-8")).hexdigest()[:8]
    return f"topic-{digest}-{ordinal:04d}"


def _format_age(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h {minutes % 60}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


def _fmt_msk(ts: datetime) -> str:
    # MSK is fixed UTC+3 without DST.
    msk = ts.astimezone(timezone(timedelta(hours=3)))
    return msk.strftime("%d.%m.%Y %H:%M MSK")


def format_shock_message(alert: dict[str, Any]) -> str:
    role = str(alert.get("role") or "").strip().lower()
    role_header = "⚡ SHOCK PRIMARY" if role == "primary" else "🌊 SHOCK AFTERSHOCK"
    symbol = str(alert.get("symbol") or "").strip().upper() or "N/A"
    direction = str(alert.get("shock_direction") or "").strip().upper() or "N/A"
    z_abs = float(alert.get("z_score_abs") or 0.0)
    abs_move = alert.get("abs_move_pct")
    abs_move_numeric = pd.to_numeric(abs_move, errors="coerce")
    abs_move_str = "n/a" if pd.isna(abs_move_numeric) else f"{float(abs_move_numeric):.3f}%"
    shock_ts = alert.get("shock_ts")
    root_ts = alert.get("root_ts")
    shock_dt = _parse_iso_utc(shock_ts)
    root_dt = _parse_iso_utc(root_ts)
    now_label = _fmt_msk(shock_dt) if shock_dt is not None else str(shock_ts or "n/a")
    root_label = _fmt_msk(root_dt) if root_dt is not None else str(root_ts or "n/a")
    age = _format_age(shock_dt - root_dt) if shock_dt is not None and root_dt is not None else "n/a"
    episode_id = str(alert.get("episode_id") or "n/a")
    episode_idx = int(alert.get("episode_event_index") or 0)
    topic_key = str(alert.get("topic_key") or "n/a")
    headline = _normalize_text(alert.get("headline"))
    url = _normalize_text(alert.get("url"))

    lines = [
        role_header,
        f"🧩 Topic: {topic_key}",
        f"📈 Symbol: {symbol}",
        f"🧭 Direction: {direction}",
        f"📊 |z|={z_abs:.2f} | move={abs_move_str}",
        f"🕒 Root: {root_label}",
        f"🕒 Now:  {now_label}",
        f"⏳ Topic age: {age}",
        f"🆔 Episode: {episode_id} #{episode_idx}",
    ]
    if headline:
        lines.append(f"📰 {headline}")
    if url:
        lines.append(f"🔗 {url}")
    return "\n".join(lines)


def apply_shock_alert_policy(
    rows: list[dict[str, Any]],
    *,
    now_utc: datetime,
    state: dict[str, Any],
    policy: ShockAlertPolicy,
) -> tuple[list[dict[str, Any]], bool]:
    sent = state.get("sent_shock_fingerprints")
    if not isinstance(sent, dict):
        sent = {}
        state["sent_shock_fingerprints"] = sent

    topics = state.get("shock_topics")
    if not isinstance(topics, dict):
        topics = {}
        state["shock_topics"] = topics

    episode_counter = int(state.get("shock_episode_counter") or 0)
    changed = False
    alerts: list[dict[str, Any]] = []

    for row in rows:
        if len(alerts) >= int(policy.max_alerts_per_cycle):
            break
        shock_ts = _parse_iso_utc(row.get("shock_ts"))
        if shock_ts is None:
            continue
        symbol = _normalize_text(row.get("symbol")).upper()
        if not symbol:
            continue
        z_score = pd.to_numeric(row.get("z_score"), errors="coerce")
        z_abs = float(abs(z_score)) if pd.notna(z_score) else 0.0
        if z_abs < float(policy.aftershock_min_z):
            continue

        fingerprint = derive_shock_fingerprint(row)
        if fingerprint in sent:
            continue

        topic_key = derive_topic_key(row)
        topic = topics.get(topic_key) if isinstance(topics.get(topic_key), dict) else None
        role = "primary"
        if topic is not None:
            last_ts = _parse_iso_utc(topic.get("last_ts"))
            if last_ts is not None:
                if shock_ts <= last_ts + timedelta(hours=int(policy.topic_reopen_after_hours)):
                    role = "aftershock"

        if role == "primary" and z_abs < float(policy.primary_min_z):
            # Do not open a new topic with weak move.
            continue
        if role == "aftershock":
            last_sent_ts = _parse_iso_utc(topic.get("last_alert_ts")) if topic else None
            if last_sent_ts is not None and shock_ts < last_sent_ts + timedelta(
                minutes=int(policy.aftershock_cooldown_minutes)
            ):
                continue

        if role == "primary":
            episode_counter += 1
            topic = {
                "episode_id": _episode_id(topic_key, episode_counter),
                "topic_key": topic_key,
                "root_ts": _iso_utc(shock_ts),
                "last_ts": _iso_utc(shock_ts),
                "last_alert_ts": _iso_utc(shock_ts),
                "event_count": 1,
                "symbol": symbol,
                "shock_direction": _normalize_text(row.get("shock_direction")).lower(),
            }
            topics[topic_key] = topic
            changed = True
        else:
            assert topic is not None
            topic["last_ts"] = _iso_utc(shock_ts)
            topic["last_alert_ts"] = _iso_utc(shock_ts)
            topic["event_count"] = int(topic.get("event_count") or 0) + 1
            changed = True

        alert = {
            "role": role,
            "topic_key": topic_key,
            "episode_id": topic["episode_id"],
            "episode_event_index": int(topic.get("event_count") or 1),
            "root_ts": topic.get("root_ts"),
            "shock_ts": _iso_utc(shock_ts),
            "symbol": symbol,
            "shock_direction": _normalize_text(row.get("shock_direction")).lower(),
            "z_score_abs": z_abs,
            "abs_move_pct": pd.to_numeric(row.get("abs_move_pct"), errors="coerce"),
            "headline": _normalize_text(
                row.get("headline")
                or row.get("selected_title")
                or row.get("v2_title")
                or row.get("broad_title")
                or row.get("title")
            ),
            "url": _normalize_text(
                row.get("url")
                or row.get("selected_url")
                or row.get("v2_url")
                or row.get("broad_url")
            ),
            "fingerprint": fingerprint,
        }
        alerts.append(alert)
        sent[fingerprint] = _iso_utc(now_utc)
        changed = True

    state["shock_episode_counter"] = episode_counter
    parsed_row_ts = [_parse_iso_utc(item.get("shock_ts")) for item in rows]
    parsed_row_ts = [item for item in parsed_row_ts if item is not None]
    if parsed_row_ts:
        state["shock_last_processed_ts"] = _iso_utc(max(parsed_row_ts))

    # Cleanup old sent fingerprints.
    ttl = timedelta(hours=int(policy.sent_fingerprint_ttl_hours))
    for key in list(sent.keys()):
        ts = _parse_iso_utc(sent.get(key))
        if ts is None or now_utc > ts + ttl:
            sent.pop(key, None)
            changed = True

    return alerts, changed
