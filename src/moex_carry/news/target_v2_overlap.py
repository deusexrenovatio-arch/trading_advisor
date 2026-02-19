from __future__ import annotations

import re
from datetime import datetime


def _normalize_episode_text(value: object, *, max_chars: int = 180) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    # Remove noisy numeric drift so repeated updates map to the same episode key.
    text = re.sub(r"\d{4}-\d{2}-\d{2}", "<date>", text)
    text = re.sub(r"\d+", "#", text)
    text = re.sub(r"\s+", " ", text)
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars]
    return text


def _parse_mechanism_tokens(value: object) -> dict[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return {}
    tokens: dict[str, str] = {}
    for chunk in raw.split("|"):
        item = str(chunk or "").strip()
        if "=" not in item:
            continue
        key, val = item.split("=", 1)
        key_norm = str(key or "").strip().lower()
        val_norm = _normalize_episode_text(val, max_chars=80)
        if key_norm and val_norm:
            tokens[key_norm] = val_norm
    return tokens


def episode_key_from_event(event: dict[str, object]) -> str:
    event_id = str(event.get("event_id") or "").strip()
    mechanism_raw = str(event.get("canonical_mechanism") or "").strip()
    summary_raw = str(event.get("canonical_summary") or "").strip()
    token_map = _parse_mechanism_tokens(mechanism_raw)
    for field in ("anchor_id", "storm_id", "incident_id", "release_id"):
        value = token_map.get(field)
        if value:
            return f"{field}:{value}"
    family = token_map.get("event_family") or token_map.get("family")
    if family:
        return f"family:{family}"
    mechanism = _normalize_episode_text(mechanism_raw, max_chars=120)
    if mechanism:
        return f"mechanism:{mechanism}"
    summary = _normalize_episode_text(summary_raw, max_chars=120)
    if summary:
        return f"summary:{summary}"
    return f"event:{event_id or 'unknown'}"


def mark_episode_aware_overlaps(rows: list[dict[str, object]]) -> int:
    overlap_rows = 0
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        horizon = str(row.get("horizon") or "").strip().lower()
        if not symbol or not horizon:
            continue
        grouped.setdefault((symbol, horizon), []).append(row)
    for items in grouped.values():
        ordered = sorted(
            items,
            key=lambda row: (
                row.get("_t0_dt") if isinstance(row.get("_t0_dt"), datetime) else datetime.min,
                str(row.get("event_id") or ""),
            ),
        )
        active_windows: list[tuple[datetime, str]] = []
        for row in ordered:
            t0 = row.get("_t0_dt")
            t1 = row.get("_t1_dt")
            episode_key = str(row.get("_episode_key") or "").strip() or f"event:{str(row.get('event_id') or '').strip()}"
            if not isinstance(t0, datetime) or not isinstance(t1, datetime):
                row["overlap_count"] = 0
                row["is_overlapped"] = False
                continue
            active_windows = [item for item in active_windows if item[0] >= t0]
            # Episode-collapse: treat updates inside one episode as primary+updates, not as cross-event overlap.
            overlap_count = sum(1 for _, key in active_windows if key != episode_key)
            row["overlap_count"] = overlap_count
            row["is_overlapped"] = bool(overlap_count > 0)
            if overlap_count > 0:
                overlap_rows += 1
            active_windows.append((t1, episode_key))
    return overlap_rows
