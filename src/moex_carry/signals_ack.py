from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


ACK_NOTE_KIND = "telegram_ack"


def _normalize_part(value: object) -> str:
    return str(value or "").strip()


def build_signal_fingerprint(
    *,
    run_id: object,
    timestamp: object,
    stock: object,
    future: object,
    signal_action: object,
) -> str:
    raw = "|".join(
        [
            _normalize_part(run_id),
            _normalize_part(timestamp),
            _normalize_part(stock),
            _normalize_part(future),
            _normalize_part(signal_action),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def build_ack_note(
    *,
    fingerprint: str,
    signal_run_id: str,
    signal_timestamp: str,
    signal_action: str,
    telegram_user_id: int,
    telegram_username: str | None,
    telegram_chat_id: int,
    acked_at: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "kind": ACK_NOTE_KIND,
        "fingerprint": str(fingerprint),
        "signal_run_id": str(signal_run_id),
        "signal_timestamp": str(signal_timestamp),
        "signal_action": str(signal_action),
        "telegram_user_id": int(telegram_user_id),
        "telegram_username": str(telegram_username) if telegram_username else None,
        "telegram_chat_id": int(telegram_chat_id),
        "acked_at": acked_at
        if isinstance(acked_at, str) and acked_at.strip()
        else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def parse_ack_note(note: object) -> dict[str, object] | None:
    if not isinstance(note, str) or not note.strip():
        return None
    try:
        payload = json.loads(note)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("kind") or "").strip() != ACK_NOTE_KIND:
        return None

    fingerprint = str(payload.get("fingerprint") or "").strip()
    if not fingerprint:
        return None

    user_id_raw = payload.get("telegram_user_id")
    try:
        telegram_user_id = int(user_id_raw) if user_id_raw is not None else None
    except (TypeError, ValueError):
        telegram_user_id = None

    chat_id_raw = payload.get("telegram_chat_id")
    try:
        telegram_chat_id = int(chat_id_raw) if chat_id_raw is not None else None
    except (TypeError, ValueError):
        telegram_chat_id = None

    username_raw = payload.get("telegram_username")
    telegram_username = (
        str(username_raw).strip() if isinstance(username_raw, str) and username_raw.strip() else None
    )

    acked_at_raw = payload.get("acked_at")
    acked_at = str(acked_at_raw).strip() if isinstance(acked_at_raw, str) and acked_at_raw.strip() else None

    return {
        "kind": ACK_NOTE_KIND,
        "fingerprint": fingerprint,
        "signal_run_id": str(payload.get("signal_run_id") or "").strip(),
        "signal_timestamp": str(payload.get("signal_timestamp") or "").strip(),
        "signal_action": str(payload.get("signal_action") or "").strip(),
        "telegram_user_id": telegram_user_id,
        "telegram_username": telegram_username,
        "telegram_chat_id": telegram_chat_id,
        "acked_at": acked_at,
    }
