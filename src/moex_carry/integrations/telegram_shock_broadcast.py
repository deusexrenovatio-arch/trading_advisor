from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from moex_carry.config import TelegramConfig
from moex_carry.shock_alert_delivery import (
    ShockAlertPolicy,
    apply_shock_alert_policy,
    format_shock_message,
    load_shock_rows,
)
from moex_carry.signals_delivery import parse_iso_utc as parse_iso


def broadcast_shock_alerts(
    *,
    cfg: TelegramConfig,
    state: dict[str, object],
    registered_chats: list[int],
    shock_feed_path: Path | None,
    send_text: Callable[[int, str], None],
    save_state: Callable[[], None],
    logger: logging.Logger,
) -> None:
    if not bool(cfg.shock_alerts_enabled):
        return
    if not registered_chats:
        return
    if shock_feed_path is None:
        logger.warning("telegram.shock_alerts_enabled=true but shock_feed_path is empty.")
        return

    since_ts = parse_iso(state.get("shock_last_processed_ts"))
    max_rows = max(int(cfg.shock_max_alerts_per_cycle or 1), 1) * 10
    rows = load_shock_rows(
        shock_feed_path,
        since_ts=since_ts,
        max_rows=max_rows,
    )
    if not rows:
        return

    now_utc = datetime.now(timezone.utc)
    policy = ShockAlertPolicy(
        primary_min_z=float(cfg.shock_primary_min_z),
        aftershock_min_z=float(cfg.shock_aftershock_min_z),
        topic_reopen_after_hours=max(int(cfg.shock_topic_reopen_after_hours), 1),
        aftershock_cooldown_minutes=max(int(cfg.shock_aftershock_cooldown_minutes), 0),
        max_alerts_per_cycle=max(int(cfg.shock_max_alerts_per_cycle), 1),
        sent_fingerprint_ttl_hours=max(int(cfg.shock_sent_fingerprint_ttl_hours), 1),
    )
    alerts, changed = apply_shock_alert_policy(
        rows,
        now_utc=now_utc,
        state=state,
        policy=policy,
    )
    if not alerts and not changed:
        return

    sent_map = state.get("sent_shock_fingerprints")
    if not isinstance(sent_map, dict):
        sent_map = {}
        state["sent_shock_fingerprints"] = sent_map
        changed = True

    for alert in alerts:
        message = format_shock_message(alert)
        delivered = False
        for chat_id in registered_chats:
            try:
                send_text(chat_id, message)
            except Exception:
                logger.exception("Failed to send shock alert to chat_id=%s", chat_id)
                continue
            delivered = True

        if not delivered:
            fingerprint = str(alert.get("fingerprint") or "").strip()
            if fingerprint and fingerprint in sent_map:
                sent_map.pop(fingerprint, None)
                changed = True

    if changed:
        save_state()
