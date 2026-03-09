from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_state_path(raw_path: str, data_dir: str | Path | None = None) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    if data_dir is None:
        return (Path.cwd() / path).resolve()
    base_dir = Path(data_dir).expanduser()
    if not base_dir.is_absolute():
        base_dir = (Path.cwd() / base_dir).resolve()
    text = str(path).replace("\\", "/")
    if text.startswith("./data/"):
        return (base_dir / text[len("./data/") :]).resolve()
    if text.startswith("data/"):
        return (base_dir / text[len("data/") :]).resolve()
    return (base_dir / path).resolve()


def empty_state() -> dict[str, object]:
    return {
        "last_update_id": 0,
        "registered_chats": {},
        "sent_fingerprints": {},
        "sent_root_fingerprints": {},
        "sent_shock_fingerprints": {},
        "sent_news_fingerprints": {},
        "hold_open_last_sent_date_by_pair": {},
        "enter_last_sent_at_by_pair": {},
        "enter_tracking_by_fingerprint": {},
        "daily_healthcheck_last_sent_date_by_chat": {},
        "pending_callbacks": {},
        "shock_topics": {},
        "root_last_processed_ts": None,
        "shock_last_processed_ts": None,
        "news_last_processed_ts": None,
        "shock_episode_counter": 0,
    }


def load_state(path: Path, *, logger: logging.Logger | None = None) -> dict[str, object]:
    if not path.exists():
        return empty_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        if logger is not None:
            logger.warning("Failed to load Telegram worker state, using empty state.")
        return empty_state()
    if not isinstance(payload, dict):
        return empty_state()

    state = empty_state()
    state["last_update_id"] = safe_int(payload.get("last_update_id")) or 0

    registered_chats: dict[str, int] = {}
    for key, value in (payload.get("registered_chats") or {}).items():
        parsed_value = safe_int(value)
        if parsed_value is not None:
            registered_chats[str(key)] = parsed_value
    state["registered_chats"] = registered_chats

    state["sent_fingerprints"] = {
        str(key): str(value)
        for key, value in (payload.get("sent_fingerprints") or {}).items()
        if isinstance(key, str) and isinstance(value, str)
    }
    for map_key in ("sent_root_fingerprints", "sent_shock_fingerprints", "sent_news_fingerprints"):
        state[map_key] = {
            str(key): str(value)
            for key, value in (payload.get(map_key) or {}).items()
            if isinstance(key, str) and isinstance(value, str)
        }

    state["hold_open_last_sent_date_by_pair"] = {
        str(key): str(value)
        for key, value in (payload.get("hold_open_last_sent_date_by_pair") or {}).items()
        if isinstance(key, str) and isinstance(value, str)
    }
    state["enter_last_sent_at_by_pair"] = {
        str(key): str(value)
        for key, value in (payload.get("enter_last_sent_at_by_pair") or {}).items()
        if isinstance(key, str) and isinstance(value, str)
    }

    raw_tracking = payload.get("enter_tracking_by_fingerprint") or {}
    if isinstance(raw_tracking, dict):
        normalized_tracking: dict[str, dict[str, object]] = {}
        for key, value in raw_tracking.items():
            if isinstance(key, str) and isinstance(value, dict):
                normalized_tracking[key] = dict(value)
        state["enter_tracking_by_fingerprint"] = normalized_tracking

    state["daily_healthcheck_last_sent_date_by_chat"] = {
        str(key): str(value)
        for key, value in (payload.get("daily_healthcheck_last_sent_date_by_chat") or {}).items()
        if isinstance(key, str) and isinstance(value, str)
    }

    callbacks = payload.get("pending_callbacks") or {}
    if isinstance(callbacks, dict):
        normalized_callbacks: dict[str, dict[str, object]] = {}
        for key, value in callbacks.items():
            if isinstance(key, str) and isinstance(value, dict):
                normalized_callbacks[key] = dict(value)
        state["pending_callbacks"] = normalized_callbacks

    shock_topics = payload.get("shock_topics") or {}
    if isinstance(shock_topics, dict):
        normalized_topics: dict[str, dict[str, object]] = {}
        for key, value in shock_topics.items():
            if isinstance(key, str) and isinstance(value, dict):
                normalized_topics[key] = dict(value)
        state["shock_topics"] = normalized_topics

    for key in ("root_last_processed_ts", "shock_last_processed_ts", "news_last_processed_ts"):
        processed_ts = payload.get(key)
        if isinstance(processed_ts, str) and processed_ts.strip():
            state[key] = processed_ts

    state["shock_episode_counter"] = safe_int(payload.get("shock_episode_counter")) or 0
    return state


def save_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
