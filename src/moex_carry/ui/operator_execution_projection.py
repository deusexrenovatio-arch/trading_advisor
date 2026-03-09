from __future__ import annotations

from datetime import datetime, timezone

from moex_carry.signal_execution_contract import (
    expand_h4a_followup_stage,
    normalize_execution_action,
    normalize_h4a_followup_stage,
    normalize_operator_execution_mode,
    normalize_signal_action_request,
)

_OPERATOR_EVENT_NOTE_KEYS = (
    "fill_ts",
    "fill_price",
    "effective_fill_price",
    "initial_loss_sl",
    "tp_limit",
    "protective_sl",
    "break_even_activation_price",
    "break_even_stop_price",
    "trail_activation_price",
    "fallback_applied",
    "recalc_applied",
    "time_stop_deadline_ts",
    "same_bar_resolution",
    "exit_reason_code",
)


def _normalize_event_datetime(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _canonical_operator_status(value: object) -> str:
    normalized = normalize_signal_action_request(value, legacy_mode=False)
    if normalized is not None:
        return normalized[0]
    return normalize_execution_action(value)


def default_operator_event_entry() -> dict[str, object]:
    return {
        "operator_execution_mode": normalize_operator_execution_mode(None),
        "h4a_followup_confirmations": {},
    }


def serialize_followup_confirmations(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, dict):
        return {}
    serialized: dict[str, dict[str, object]] = {}
    for raw_stage, raw_payload in value.items():
        stage = normalize_h4a_followup_stage(raw_stage)
        if stage is None:
            continue
        item = dict(raw_payload) if isinstance(raw_payload, dict) else {}
        confirmed_at = _normalize_event_datetime(item.get("confirmed_at"))
        if confirmed_at is not None:
            item["confirmed_at"] = confirmed_at.isoformat()
        serialized[stage] = item
    return serialized


def _update_operator_event_field(
    entry: dict[str, object],
    *,
    field_prefix: str,
    event_at: datetime,
    actor: str | None,
) -> None:
    existing_ts = _normalize_event_datetime(entry.get(f"{field_prefix}_at"))
    if existing_ts is not None and event_at < existing_ts:
        return
    entry[f"{field_prefix}_at"] = event_at
    entry[f"{field_prefix}_by"] = actor


def apply_operator_event(
    entry: dict[str, object],
    *,
    status: str,
    event_at: datetime,
    actor: str | None,
    note_payload: dict[str, object] | None = None,
) -> None:
    canonical_status = _canonical_operator_status(status)
    legacy_consumes_intent = bool(
        isinstance(note_payload, dict) and note_payload.get("legacy_consumes_intent")
    )
    if canonical_status == "confirm_followup":
        if isinstance(note_payload, dict):
            stage = normalize_h4a_followup_stage(note_payload.get("h4a_stage"))
            if stage is not None:
                confirmations_raw = entry.get("h4a_followup_confirmations")
                confirmations = dict(confirmations_raw) if isinstance(confirmations_raw, dict) else {}
                for expanded_stage in expand_h4a_followup_stage(stage):
                    confirmation_entry = dict(confirmations.get(expanded_stage) or {})
                    confirmation_entry["confirmed_at"] = event_at
                    if actor is not None:
                        confirmation_entry["confirmed_by"] = actor
                    reason_code = str(note_payload.get("reason_code") or "").strip()
                    note_value = str(note_payload.get("note") or "").strip()
                    if reason_code:
                        confirmation_entry["reason_code"] = reason_code
                    if note_value:
                        confirmation_entry["note"] = note_value
                    confirmations[expanded_stage] = confirmation_entry
                entry["h4a_followup_confirmations"] = confirmations
        return

    field_prefix = {
        "mark_viewed": "signal_viewed",
        "enter_submitted": "enter_submitted",
        "enter_filled": "enter_filled",
        "entry_cancelled": "entry_cancelled",
        "exit_submitted": "exit_submitted",
        "exit_filled": "exit_filled",
        "manual_override": "manual_override",
    }.get(canonical_status)
    if field_prefix is not None:
        _update_operator_event_field(
            entry,
            field_prefix=field_prefix,
            event_at=event_at,
            actor=actor,
        )

    if canonical_status == "mark_viewed" and legacy_consumes_intent:
        entry["signal_used"] = True
        _update_operator_event_field(
            entry,
            field_prefix="signal_used",
            event_at=event_at,
            actor=actor,
        )

    if canonical_status in {"enter_submitted", "enter_filled", "entry_cancelled", "manual_override"}:
        entry["signal_used"] = True
        _update_operator_event_field(
            entry,
            field_prefix="signal_used",
            event_at=event_at,
            actor=actor,
        )

    existing_status_at = _normalize_event_datetime(entry.get("operator_status_at"))
    if existing_status_at is None or event_at >= existing_status_at:
        entry["operator_signal_status"] = canonical_status
        entry["operator_status_at"] = event_at
        entry["operator_status_by"] = actor

    mode_hint = note_payload.get("operator_execution_mode") if isinstance(note_payload, dict) else None
    if isinstance(note_payload, dict):
        for key in _OPERATOR_EVENT_NOTE_KEYS:
            if key in note_payload:
                entry[key] = note_payload.get(key)
    if canonical_status == "manual_override":
        mode_hint = "manual_override"
    if mode_hint is not None or "operator_execution_mode" not in entry:
        entry["operator_execution_mode"] = normalize_operator_execution_mode(mode_hint)


def register_operator_event(
    *,
    operator_events_by_fingerprint: dict[str, dict[str, object]],
    operator_events_by_pair: dict[tuple[str, str], dict[str, object]],
    fingerprint: str | None,
    pair_key: tuple[str, str] | None,
    status: str,
    event_at: datetime,
    actor: str | None,
    note_payload: dict[str, object] | None = None,
) -> None:
    entries: list[dict[str, object]] = []
    fingerprint_key = str(fingerprint or "").strip()
    if fingerprint_key:
        entries.append(
            operator_events_by_fingerprint.setdefault(
                fingerprint_key,
                default_operator_event_entry(),
            )
        )
    if (
        isinstance(pair_key, tuple)
        and len(pair_key) == 2
        and all(isinstance(item, str) and item.strip() for item in pair_key)
    ):
        normalized_pair_key = (pair_key[0].strip(), pair_key[1].strip())
        pair_entry = operator_events_by_pair.setdefault(
            normalized_pair_key,
            default_operator_event_entry(),
        )
        if not any(existing is pair_entry for existing in entries):
            entries.append(pair_entry)
    for entry in entries:
        apply_operator_event(
            entry,
            status=status,
            event_at=event_at,
            actor=actor,
            note_payload=note_payload,
        )
