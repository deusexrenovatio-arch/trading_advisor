from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, Mapping, MutableMapping

from moex_carry.signal_execution_contract import (
    H4A_FOLLOWUP_TIME_STOP_REMINDER_LEAD_MINUTES,
    build_h4a_followup_state,
    infer_fill_side_action,
    is_h4a_followup_stage_confirmed,
)


def _to_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fmt_timestamp(value: object) -> str:
    parsed = _parse_iso(value)
    if parsed is None:
        return "n/a"
    return parsed.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def _fmt_price(value: object) -> str:
    parsed = _to_float(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.4f}"


def _pair_label(row: Mapping[str, object]) -> str:
    stock = str(row.get("stock") or "").strip() or "N/A"
    future = str(row.get("future") or "").strip() or "N/A"
    return f"{stock}/{future}"


def _pair_id(row: Mapping[str, object]) -> str:
    stock = str(row.get("stock") or "").strip()
    future = str(row.get("future") or "").strip()
    return f"{stock}__{future}"


def _trail_offset_ticks(row: Mapping[str, object]) -> int:
    execution_contract = row.get("execution_contract")
    contract = execution_contract if isinstance(execution_contract, Mapping) else {}
    return int(_to_float(contract.get("trail_offset_ticks")) or 0)


def _entry_fallback_after_minutes(row: Mapping[str, object]) -> int:
    execution_contract = row.get("execution_contract")
    contract = execution_contract if isinstance(execution_contract, Mapping) else {}
    return int(_to_float(contract.get("entry_fallback_after_minutes")) or 0)


def _monitor_price_text(followup_state: Mapping[str, object]) -> str:
    current_price = followup_state.get("current_price")
    current_price_source = str(followup_state.get("current_price_source") or "").strip()
    if _to_float(current_price) is None:
        return "n/a"
    if current_price_source:
        return f"{_fmt_price(current_price)} ({current_price_source})"
    return _fmt_price(current_price)


def _followup_confirmed(followup_state: Mapping[str, object], *, stage: str) -> bool:
    confirmations = followup_state.get("confirmations")
    return is_h4a_followup_stage_confirmed(confirmations, stage=stage)


def has_post_fill_state(row: Mapping[str, object]) -> bool:
    followup_state = build_h4a_followup_state(row=row)
    return bool(followup_state.get("post_fill_active"))


def format_post_fill_message(row: Mapping[str, object]) -> str:
    baseline_id = str(row.get("baseline_id") or "").strip() or "H4A_CAP_OFF"
    lines = [
        f"🔃 H4A post-fill: {_pair_label(row)}",
        f"• Baseline: {baseline_id}",
        (
            "• Fill: "
            f"{_fmt_price(row.get('effective_fill_price') or row.get('fill_price'))} @ "
            f"{_fmt_timestamp(row.get('fill_ts'))}"
        ),
        f"• Initial SL: {_fmt_price(row.get('initial_loss_sl'))}",
        f"• TP limit: {_fmt_price(row.get('tp_limit'))}",
        f"• Protective SL now: {_fmt_price(row.get('protective_sl'))}",
        (
            "• Break-even: trigger "
            f"{_fmt_price(row.get('break_even_activation_price'))} -> stop "
            f"{_fmt_price(row.get('break_even_stop_price'))}"
        ),
        (
            "• Trailing: trigger "
            f"{_fmt_price(row.get('trail_activation_price'))} -> offset "
            f"{_trail_offset_ticks(row)} ticks"
        ),
        f"• Time stop: {_fmt_timestamp(row.get('time_stop_deadline_ts'))}",
    ]
    if bool(row.get("fallback_applied")):
        lines.append("• Entry fallback already applied and must stay visible in audit.")
    same_bar_resolution = str(row.get("same_bar_resolution") or "").strip()
    if same_bar_resolution:
        lines.append(f"• Same-bar resolution: {same_bar_resolution}")
    if not bool(row.get("recalc_applied")):
        lines.append(
            "⚠️ Auto-recalculation did not finish. If the position is managed outside H4A, use Manual override."
        )
    else:
        lines.append("• Apply the recalculated bracket on broker side, then press Confirm.")
    return "\n".join(lines)


def format_entry_fallback_message(
    row: Mapping[str, object],
    *,
    followup_state: Mapping[str, object],
) -> str:
    fallback_due_at = followup_state.get("entry_fallback_due_at")
    fallback_after_minutes = _entry_fallback_after_minutes(row)
    lines = [
        f"⏳ H4A fallback timeout: {_pair_label(row)}",
        f"• LIMIT is still not filled after {fallback_after_minutes} minutes from enter_submitted.",
        f"• Deadline: {_fmt_timestamp(fallback_due_at)}",
        "• Replace the LIMIT with a marketable order or cancel the entry and log the deviation.",
        "• After the decision is applied, press Confirm. If you continue outside H4A, use Manual override.",
    ]
    return "\n".join(lines)


def format_break_even_trailing_message(
    row: Mapping[str, object],
    *,
    followup_state: Mapping[str, object],
    break_even_due: bool,
    trail_due: bool,
) -> str:
    side_action = str(row.get("side_action") or "").strip().upper()
    if side_action not in {"BUY", "SELL"}:
        side_action = infer_fill_side_action(row=row, side_action=None)
    lines = [
        f"🛡 H4A trigger reached: {_pair_label(row)}",
        f"• Current price: {_monitor_price_text(followup_state)}",
    ]
    if break_even_due:
        lines.append(
            "• Break-even trigger reached: "
            f"{_fmt_price(row.get('break_even_activation_price'))} -> move stop to "
            f"{_fmt_price(row.get('break_even_stop_price'))}."
        )
    if trail_due:
        lines.append(
            "• Trailing is active: keep stop "
            f"{_trail_offset_ticks(row)} ticks behind the best favorable price."
        )
    lines.append(f"• Side: {side_action}")
    lines.append("• After the stop update is applied, press Confirm. If baseline is broken, use Manual override.")
    return "\n".join(lines)


def format_time_stop_message(row: Mapping[str, object], *, overdue: bool) -> str:
    prefix = "⛔ H4A time stop overdue" if overdue else "⏰ H4A time stop soon"
    lines = [
        f"{prefix}: {_pair_label(row)}",
        f"• Deadline: {_fmt_timestamp(row.get('time_stop_deadline_ts'))}",
        f"• Protective SL: {_fmt_price(row.get('protective_sl'))}",
        f"• TP limit: {_fmt_price(row.get('tp_limit'))}",
    ]
    if overdue:
        lines.append("• Close the position and record exit_filled with reason time_stop_180m.")
    else:
        lines.append("• If the position stays open until deadline, close it and log time_stop_180m.")
    lines.append("• After the action is applied, press Confirm. If the position stays outside H4A, use Manual override.")
    return "\n".join(lines)


def _intent_id_from_row(row: Mapping[str, object]) -> str | None:
    intent_payload = row.get("intent")
    if not isinstance(intent_payload, Mapping):
        return None
    intent_id = str(intent_payload.get("intent_id") or "").strip()
    return intent_id or None


def _build_base_callback_payload(
    row: Mapping[str, object],
    *,
    token: str,
    chat_id: int,
    now_iso: str,
    stage: str,
) -> dict[str, object]:
    pair_id = _pair_id(row)
    return {
        "token": token,
        "fingerprint": row.get("signal_fingerprint"),
        "run_id": row.get("run_id"),
        "timestamp": row.get("timestamp"),
        "stock": row.get("stock"),
        "future": row.get("future"),
        "pair_id": pair_id,
        "entity_type": "pair",
        "entity_id": pair_id,
        "intent_id": _intent_id_from_row(row),
        "signal_id": row.get("signal_id"),
        "signal_action": row.get("signal_action"),
        "signal_direction": row.get("signal_direction"),
        "strategy_id": row.get("strategy_id"),
        "strategy_type": row.get("strategy_type"),
        "strategy_stream": row.get("strategy_stream"),
        "chat_id": chat_id,
        "created_at": now_iso,
        "h4a_stage": stage,
    }


def _build_confirm_followup_callback(
    row: Mapping[str, object],
    *,
    token: str,
    chat_id: int,
    now_iso: str,
    stage: str,
) -> dict[str, object]:
    payload = _build_base_callback_payload(
        row,
        token=token,
        chat_id=chat_id,
        now_iso=now_iso,
        stage=stage,
    )
    payload.update(
        {
            "callback_action": "confirm_followup",
            "idempotency_key": f"telegram-confirm_followup:{token}",
            "reason_code": f"telegram_confirm_followup_{stage}",
            "note": f"telegram_callback:confirm_followup:{stage}",
        }
    )
    return payload


def _build_manual_override_callback(
    row: Mapping[str, object],
    *,
    token: str,
    chat_id: int,
    now_iso: str,
    stage: str,
) -> dict[str, object]:
    payload = _build_base_callback_payload(
        row,
        token=token,
        chat_id=chat_id,
        now_iso=now_iso,
        stage=stage,
    )
    payload.update(
        {
            "callback_action": "manual_override",
            "idempotency_key": f"telegram-manual_override:{token}",
            "reason_code": f"telegram_manual_override_{stage}",
            "note": f"telegram_callback:manual_override:{stage}",
        }
    )
    return payload


def _send_stage_message(
    *,
    row: Mapping[str, object],
    target_chats: list[int],
    callbacks: MutableMapping[str, object],
    now_iso: str,
    stage: str,
    text: str,
    send_followup_message: Callable[..., None],
    logger: logging.Logger,
) -> bool:
    delivered = False
    for chat_id in target_chats:
        confirm_token = uuid.uuid4().hex[:10]
        override_token = uuid.uuid4().hex[:10]
        callbacks[confirm_token] = _build_confirm_followup_callback(
            row,
            token=confirm_token,
            chat_id=chat_id,
            now_iso=now_iso,
            stage=stage,
        )
        callbacks[override_token] = _build_manual_override_callback(
            row,
            token=override_token,
            chat_id=chat_id,
            now_iso=now_iso,
            stage=stage,
        )
        actions = [
            {"text": "✅ Confirm", "callback_action": "confirm_followup", "token": confirm_token},
            {"text": "⚠️ Manual override", "callback_action": "manual_override", "token": override_token},
        ]
        try:
            send_followup_message(chat_id=chat_id, text=text, actions=actions)
        except Exception:
            callbacks.pop(confirm_token, None)
            callbacks.pop(override_token, None)
            logger.exception("Failed to send H4A follow-up stage=%s to chat_id=%s", stage, chat_id)
            continue
        delivered = True
    return delivered


def broadcast_h4a_followups(
    *,
    rows: list[dict[str, object]],
    target_chats: list[int],
    callbacks: MutableMapping[str, object],
    post_fill_map: MutableMapping[str, object],
    entry_fallback_map: MutableMapping[str, object],
    break_even_map: MutableMapping[str, object],
    trailing_map: MutableMapping[str, object],
    reminder_map: MutableMapping[str, object],
    overdue_map: MutableMapping[str, object],
    now_dt: datetime,
    now_iso: str,
    send_followup_message: Callable[..., None],
    logger: logging.Logger,
) -> bool:
    changed = False
    for row in rows:
        fingerprint = str(row.get("signal_fingerprint") or "").strip()
        if not fingerprint:
            continue
        followup_state = build_h4a_followup_state(row=row, now_utc=now_dt)
        if not followup_state:
            continue
        resolved_row = dict(row)
        resolved_row["h4a_followup"] = followup_state

        if (
            bool(followup_state.get("entry_fallback_due"))
            and fingerprint not in entry_fallback_map
            and not _followup_confirmed(followup_state, stage="entry_fallback_due")
        ):
            if _send_stage_message(
                row=resolved_row,
                target_chats=target_chats,
                callbacks=callbacks,
                now_iso=now_iso,
                stage="entry_fallback_due",
                text=format_entry_fallback_message(resolved_row, followup_state=followup_state),
                send_followup_message=send_followup_message,
                logger=logger,
            ):
                entry_fallback_map[fingerprint] = now_iso
                changed = True

        if (
            bool(followup_state.get("post_fill_active"))
            and fingerprint not in post_fill_map
            and not _followup_confirmed(followup_state, stage="post_fill_packet")
        ):
            if _send_stage_message(
                row=resolved_row,
                target_chats=target_chats,
                callbacks=callbacks,
                now_iso=now_iso,
                stage="post_fill_packet",
                text=format_post_fill_message(resolved_row),
                send_followup_message=send_followup_message,
                logger=logger,
            ):
                post_fill_map[fingerprint] = now_iso
                changed = True

        if str(row.get("operator_execution_mode") or "").strip().lower() == "manual_override":
            continue
        if str(row.get("position_state") or "").strip().lower() != "open":
            continue

        break_even_due = bool(followup_state.get("break_even_trigger_reached"))
        trail_due = bool(followup_state.get("trail_trigger_reached"))
        break_even_unsent = (
            break_even_due
            and fingerprint not in break_even_map
            and not _followup_confirmed(followup_state, stage="break_even_due")
        )
        trailing_unsent = (
            trail_due
            and fingerprint not in trailing_map
            and not _followup_confirmed(followup_state, stage="trailing_due")
        )
        if break_even_unsent or trailing_unsent:
            stage = (
                "break_even_trailing_due"
                if break_even_unsent and trailing_unsent
                else ("break_even_due" if break_even_unsent else "trailing_due")
            )
            if _send_stage_message(
                row=resolved_row,
                target_chats=target_chats,
                callbacks=callbacks,
                now_iso=now_iso,
                stage=stage,
                text=format_break_even_trailing_message(
                    resolved_row,
                    followup_state=followup_state,
                    break_even_due=break_even_unsent,
                    trail_due=trailing_unsent,
                ),
                send_followup_message=send_followup_message,
                logger=logger,
            ):
                if break_even_unsent:
                    break_even_map[fingerprint] = now_iso
                if trailing_unsent:
                    trailing_map[fingerprint] = now_iso
                changed = True

        if (
            bool(followup_state.get("time_stop_overdue"))
            and fingerprint not in overdue_map
            and not _followup_confirmed(followup_state, stage="time_stop_overdue")
        ):
            if _send_stage_message(
                row=resolved_row,
                target_chats=target_chats,
                callbacks=callbacks,
                now_iso=now_iso,
                stage="time_stop_overdue",
                text=format_time_stop_message(resolved_row, overdue=True),
                send_followup_message=send_followup_message,
                logger=logger,
            ):
                overdue_map[fingerprint] = now_iso
                changed = True
            continue

        if (
            bool(followup_state.get("time_stop_reminder_due"))
            and fingerprint not in reminder_map
            and not _followup_confirmed(followup_state, stage="time_stop_due")
        ):
            if _send_stage_message(
                row=resolved_row,
                target_chats=target_chats,
                callbacks=callbacks,
                now_iso=now_iso,
                stage="time_stop_due",
                text=format_time_stop_message(resolved_row, overdue=False),
                send_followup_message=send_followup_message,
                logger=logger,
            ):
                reminder_map[fingerprint] = now_iso
                changed = True
    return changed


__all__ = [
    "H4A_FOLLOWUP_TIME_STOP_REMINDER_LEAD_MINUTES",
    "broadcast_h4a_followups",
    "format_break_even_trailing_message",
    "format_entry_fallback_message",
    "format_post_fill_message",
    "format_time_stop_message",
    "has_post_fill_state",
]
