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


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


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
            parsed = None
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
            _normalize_text(row.get("story_id") or row.get("story_key")),
            _normalize_text(row.get("commodity_scope")),
            _normalize_text(row.get("published_at_utc")),
            _normalize_text(row.get("url")),
            _normalize_text(row.get("title") or row.get("headline")),
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


def group_story_alerts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            _normalize_text(row.get("story_id") or row.get("story_key"))
            or _normalize_text(row.get("article_id"))
            or _normalize_text(row.get("url"))
            or derive_news_fingerprint(row)
        )
        grouped.setdefault(key, []).append(dict(row))

    alerts: list[dict[str, Any]] = []
    for key, items in grouped.items():
        ordered = sorted(
            items,
            key=lambda item: (
                _to_float(item.get("commodity_link_score"), default=_to_float(item.get("confidence"))),
                _to_float(item.get("impact_score")),
                _to_float(item.get("confidence")),
                _normalize_text(item.get("published_at_utc")),
            ),
            reverse=True,
        )
        lead = dict(ordered[0])
        story_scope_rows: list[dict[str, Any]] = []
        seen_commodities: set[str] = set()
        for item in ordered:
            commodity = _normalize_text(item.get("commodity")).upper()
            if not commodity or commodity in seen_commodities:
                continue
            story_scope_rows.append(
                {
                    "commodity": commodity,
                    "commodity_link_score": _to_float(
                        item.get("commodity_link_score"),
                        default=_to_float(item.get("confidence")),
                    ),
                    "link_reason": _normalize_text(item.get("link_reason")),
                    "link_evidence_json": _normalize_text(item.get("link_evidence_json")),
                }
            )
            seen_commodities.add(commodity)
        lead["story_id"] = _normalize_text(lead.get("story_id") or lead.get("story_key") or key)
        lead["story_scope_rows"] = story_scope_rows
        lead["commodity_scope"] = ",".join(item["commodity"] for item in story_scope_rows)
        lead["is_multi_commodity"] = len(story_scope_rows) > 1
        if story_scope_rows:
            lead["lead_commodity"] = story_scope_rows[0]["commodity"]
            lead["lead_link_score"] = story_scope_rows[0]["commodity_link_score"]
            lead["commodity"] = story_scope_rows[0]["commodity"]
            lead["commodity_link_score"] = story_scope_rows[0]["commodity_link_score"]
        alerts.append(lead)

    alerts.sort(key=lambda item: _normalize_text(item.get("published_at_utc")), reverse=True)
    return alerts


def _format_msk(ts: datetime) -> str:
    msk = ts.astimezone(timezone(timedelta(hours=3)))
    return msk.strftime("%d.%m.%Y %H:%M MSK")


def format_news_message(alert: dict[str, Any]) -> str:
    published_dt = _parse_iso_utc(alert.get("published_at_utc"))
    published_label = _format_msk(published_dt) if published_dt is not None else "n/a"
    lead_commodity = _normalize_text(alert.get("lead_commodity") or alert.get("commodity")).upper() or "N/A"
    direction = _normalize_text(alert.get("direction")).lower()
    if direction in {"up", "long", "bullish", "increase"}:
        direction_label = "UP"
    elif direction in {"down", "short", "bearish", "decrease"}:
        direction_label = "DOWN"
    else:
        direction_label = "NEUTRAL"
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
    story_id = _normalize_text(alert.get("story_id") or alert.get("story_key"))
    reason_terms_up = _coerce_reason_terms(alert.get("reason_terms_up"))
    reason_terms_down = _coerce_reason_terms(alert.get("reason_terms_down"))
    cause_classification = _normalize_text(alert.get("cause_classification")).lower() or "unknown"
    cause_event = _normalize_text(alert.get("cause_event")).lower()
    cause_route_key = _normalize_text(alert.get("cause_route_key"))
    cause_claim_status = _normalize_text(alert.get("cause_claim_status")).lower() or "unknown"
    cause_entities = _coerce_reason_terms(alert.get("cause_entities_json"))
    fundamental_score = _to_float(alert.get("fundamental_score"))
    cause_confidence = _to_float(alert.get("cause_confidence"))
    is_primary_cause = _to_bool(alert.get("is_primary_cause"))
    lead_link_score = _to_float(
        alert.get("lead_link_score"),
        default=_to_float(alert.get("commodity_link_score"), default=confidence),
    )
    story_scope_rows = alert.get("story_scope_rows")
    if not isinstance(story_scope_rows, list):
        story_scope_rows = []
    commodities_label = ", ".join(
        f"{_normalize_text(item.get('commodity')).upper()} ({_to_float(item.get('commodity_link_score')):.2f})"
        for item in story_scope_rows
        if _normalize_text(item.get("commodity"))
    ) or lead_commodity
    evidence_parts: list[str] = []
    for value in (reason_terms_up, reason_terms_down, cause_entities):
        if value:
            evidence_parts.append(value)
    for item in story_scope_rows:
        reason = _normalize_text(item.get("link_reason"))
        if reason:
            evidence_parts.append(reason)
        evidence_terms = _coerce_reason_terms(item.get("link_evidence_json"))
        if evidence_terms:
            evidence_parts.append(evidence_terms)
    evidence = ", ".join(part for part in evidence_parts if part)
    url = _normalize_text(alert.get("url"))

    lines = [
        "NEWS DISCOVERY ALERT",
        f"Published: {published_label}",
        f"Commodities: {commodities_label}",
        f"Lead link: {lead_commodity} ({lead_link_score:.2f})",
        f"Direction: {direction_label} | Impact: {impact:.3f} | Confidence: {confidence:.3f} | Severity: {severity}",
        f"Source: {source_label}",
    ]
    if story_id:
        lines.append(f"Story: {story_id}")
    if headline:
        lines.append(f"Headline: {headline}")
    lines.append(
        "Cause: "
        f"{cause_classification.upper()} | event={cause_event or 'n/a'} | route={cause_route_key or 'n/a'} "
        f"| fundamental={fundamental_score:.2f} | cause_conf={cause_confidence:.2f} "
        f"| primary={'yes' if is_primary_cause else 'no'} | claim={cause_claim_status}"
    )
    if evidence:
        lines.append(f"Evidence: {evidence}")
    if url:
        lines.append(f"URL: {url}")
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

    grouped_rows = group_story_alerts(rows)
    if not grouped_rows:
        return

    now_utc = datetime.now(timezone.utc)
    alerts, changed = apply_news_alert_policy(
        grouped_rows,
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
