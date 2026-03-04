from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from moex_carry.config import TelegramConfig
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


def _coerce_reason_terms(value: object) -> str:
    if isinstance(value, (list, tuple, set)):
        parts = [_normalize_text(item) for item in value]
        return ", ".join(part for part in parts if part)
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("[") and raw.endswith("]"):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return _normalize_text(raw)
        if isinstance(parsed, list):
            parts = [_normalize_text(item) for item in parsed]
            return ", ".join(part for part in parts if part)
    return _normalize_text(raw)


def _truncate_with_ellipsis(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: max(limit - 3, 0)].rstrip() + "..."


def derive_news_fingerprint(row: dict[str, Any]) -> str:
    payload = "|".join(
        [
            _normalize_text(row.get("published_at_utc")),
            _normalize_text(row.get("commodity")).upper(),
            _normalize_text(row.get("direction")).lower(),
            f"{_to_float(row.get('impact_score')):.4f}",
            f"{_to_float(row.get('confidence')):.4f}",
            _normalize_text(row.get("title") or row.get("headline")),
            _normalize_text(row.get("url")),
        ]
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"news:{digest}"


def load_news_rows(
    feed_path: Path,
    *,
    since_ts: datetime | None = None,
    max_rows: int = 1000,
    min_impact_score: float = 0.0,
    min_confidence: float = 0.0,
) -> list[dict[str, Any]]:
    if not feed_path.exists():
        return []
    df = pd.read_csv(feed_path)
    if df.empty:
        return []

    ts_col = None
    for candidate in ("published_at_utc", "published_at", "timestamp", "ts"):
        if candidate in df.columns:
            ts_col = candidate
            break
    if ts_col is None:
        return []

    df["_published_ts_dt"] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    df = df.dropna(subset=["_published_ts_dt"]).sort_values("_published_ts_dt")
    if since_ts is not None:
        df = df[df["_published_ts_dt"] > since_ts]
    if df.empty:
        return []

    if "impact_score" in df.columns:
        df = df[pd.to_numeric(df["impact_score"], errors="coerce").fillna(0.0) >= float(min_impact_score)]
    if "confidence" in df.columns:
        df = df[pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0) >= float(min_confidence)]
    if df.empty:
        return []

    if max_rows > 0 and len(df) > max_rows:
        df = df.tail(max_rows)

    rows: list[dict[str, Any]] = []
    for _, item in df.iterrows():
        row = {str(key): item[key] for key in df.columns if key != "_published_ts_dt"}
        row["published_at_utc"] = _iso_utc(item["_published_ts_dt"].to_pydatetime())
        rows.append(row)
    return rows


def _format_msk(ts: datetime) -> str:
    msk = ts.astimezone(timezone(timedelta(hours=3)))
    return msk.strftime("%d.%m.%Y %H:%M MSK")


def format_news_message(alert: dict[str, Any]) -> str:
    published_dt = _parse_iso_utc(alert.get("published_at_utc"))
    published_label = _format_msk(published_dt) if published_dt is not None else "n/a"
    commodity = _normalize_text(alert.get("commodity")).upper() or "N/A"
    direction = _normalize_text(alert.get("direction")).lower()
    if direction in {"up", "long", "bullish", "increase"}:
        direction_label = "⬆️ Рост"
    elif direction in {"down", "short", "bearish", "decrease"}:
        direction_label = "⬇️ Снижение"
    else:
        direction_label = "➡️ Нейтрально"
    severity = _normalize_text(alert.get("severity")).lower() or "n/a"
    impact = _to_float(alert.get("impact_score"))
    confidence = _to_float(alert.get("confidence"))
    source_name = _normalize_text(alert.get("source_name")) or "n/a"
    provider = _normalize_text(alert.get("provider"))
    source_label = f"{source_name} ({provider})" if provider else source_name
    headline = _truncate_with_ellipsis(
        _normalize_text(alert.get("title") or alert.get("headline")),
        limit=200,
    )
    story_key = _normalize_text(alert.get("story_key"))
    reason_terms_up = _coerce_reason_terms(alert.get("reason_terms_up"))
    reason_terms_down = _coerce_reason_terms(alert.get("reason_terms_down"))
    url = _normalize_text(alert.get("url"))

    lines = [
        "📰 Новостной импакт-сигнал (NEWS IMPACT ALERT)",
        f"🧷 Товар: {commodity} | 🧭 Направление: {direction_label}",
        f"Commodity: {commodity} | Direction: {direction.upper() or 'N/A'}",
        f"📊 Импакт: {impact:.3f} | Доверие: {confidence:.3f} | Серьёзность: {severity}",
        f"🕒 Публикация: {published_label}",
        f"🏷️ Источник: {source_label}",
    ]
    if story_key:
        lines.append(f"🧬 История: {story_key}")
    if headline:
        lines.append(f"🗞️ Заголовок: {headline}")
    if reason_terms_up:
        lines.append(f"✅ Драйверы роста: {reason_terms_up}")
    if reason_terms_down:
        lines.append(f"⚠️ Драйверы снижения: {reason_terms_down}")
    if url:
        lines.append(f"🔗 Ссылка: {url}")
    return "\n".join(lines)


def apply_news_alert_policy(
    rows: list[dict[str, Any]],
    *,
    now_utc: datetime,
    state: dict[str, Any],
    max_alerts_per_cycle: int,
    sent_fingerprint_ttl_hours: int,
) -> tuple[list[dict[str, Any]], bool]:
    sent = state.get("sent_news_fingerprints")
    if not isinstance(sent, dict):
        sent = {}
        state["sent_news_fingerprints"] = sent

    alerts: list[dict[str, Any]] = []
    changed = False
    for row in rows:
        if len(alerts) >= int(max_alerts_per_cycle):
            break
        published_ts = _parse_iso_utc(row.get("published_at_utc"))
        if published_ts is None:
            continue
        fingerprint = derive_news_fingerprint(row)
        if fingerprint in sent:
            continue
        alert = dict(row)
        alert["fingerprint"] = fingerprint
        alerts.append(alert)
        sent[fingerprint] = _iso_utc(now_utc)
        changed = True

    parsed_row_ts = [_parse_iso_utc(item.get("published_at_utc")) for item in rows]
    parsed_row_ts = [item for item in parsed_row_ts if item is not None]
    if parsed_row_ts:
        state["news_last_processed_ts"] = _iso_utc(max(parsed_row_ts))
        changed = True

    ttl = timedelta(hours=max(int(sent_fingerprint_ttl_hours), 1))
    for key in list(sent.keys()):
        ts = _parse_iso_utc(sent.get(key))
        if ts is None or now_utc > ts + ttl:
            sent.pop(key, None)
            changed = True

    return alerts, changed


def broadcast_news_alerts(
    *,
    cfg: TelegramConfig,
    state: dict[str, object],
    registered_chats: list[int],
    news_feed_path: Path | None,
    send_text: Callable[[int, str], None],
    save_state: Callable[[], None],
    logger: logging.Logger,
) -> None:
    if not bool(cfg.news_alerts_enabled):
        return
    if not registered_chats:
        return
    if news_feed_path is None:
        logger.warning("telegram.news_alerts_enabled=true but news_feed_path is empty.")
        return

    since_ts = parse_iso(state.get("news_last_processed_ts"))
    max_rows = max(int(cfg.news_max_alerts_per_cycle or 1), 1) * 20
    rows = load_news_rows(
        news_feed_path,
        since_ts=since_ts,
        max_rows=max_rows,
        min_impact_score=float(cfg.news_min_impact_score),
        min_confidence=float(cfg.news_min_confidence),
    )
    if not rows:
        return

    now_utc = datetime.now(timezone.utc)
    alerts, changed = apply_news_alert_policy(
        rows,
        now_utc=now_utc,
        state=state,
        max_alerts_per_cycle=max(int(cfg.news_max_alerts_per_cycle), 1),
        sent_fingerprint_ttl_hours=max(int(cfg.news_sent_fingerprint_ttl_hours), 1),
    )
    if not alerts and not changed:
        return

    sent_map = state.get("sent_news_fingerprints")
    if not isinstance(sent_map, dict):
        sent_map = {}
        state["sent_news_fingerprints"] = sent_map
        changed = True

    for alert in alerts:
        message = format_news_message(alert)
        delivered = False
        for chat_id in registered_chats:
            try:
                send_text(chat_id, message)
            except Exception:
                logger.exception("Failed to send news alert to chat_id=%s", chat_id)
                continue
            delivered = True

        if not delivered:
            fingerprint = str(alert.get("fingerprint") or "").strip()
            if fingerprint and fingerprint in sent_map:
                sent_map.pop(fingerprint, None)
                changed = True

    if changed:
        save_state()
