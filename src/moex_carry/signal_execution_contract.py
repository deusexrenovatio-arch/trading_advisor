from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Mapping


ACTIVE_BASELINE_ID = "H4A_CAP_OFF"
REFERENCE_BASELINE_ID = "O1"
OPERATOR_EXECUTION_MODE_BASELINE = "baseline_h4a"
OPERATOR_EXECUTION_MODE_MANUAL_OVERRIDE = "manual_override"
SAME_BAR_POLICY_SOURCE = "simulator_only"
SAME_BAR_RESOLUTION_LIVE = "live_timestamp"
SAME_BAR_RESOLUTION_BROKER = "broker_timestamp"
SAME_BAR_RESOLUTION_EXCHANGE = "exchange_timestamp"
SAME_BAR_RESOLUTION_AMBIGUOUS = "same_bar_ambiguous"
H4A_FOLLOWUP_TIME_STOP_REMINDER_LEAD_MINUTES = 15
H4A_FOLLOWUP_STAGES = frozenset(
    {
        "entry_fallback_due",
        "post_fill_packet",
        "break_even_due",
        "trailing_due",
        "break_even_trailing_due",
        "time_stop_due",
        "time_stop_overdue",
    }
)

VALID_SAME_BAR_RESOLUTIONS = frozenset(
    {
        SAME_BAR_RESOLUTION_LIVE,
        SAME_BAR_RESOLUTION_BROKER,
        SAME_BAR_RESOLUTION_EXCHANGE,
        SAME_BAR_RESOLUTION_AMBIGUOUS,
    }
)
H4A_EXIT_REASON_CODES = frozenset(
    {
        "tp_limit",
        "initial_loss_sl",
        "protective_sl",
        "time_stop_180m",
        "same_bar_ambiguous",
        "entry_fallback_market",
        "manual_override",
    }
)
_H4A_FOLLOWUP_STAGE_COMPONENTS: dict[str, tuple[str, ...]] = {
    "entry_fallback_due": ("entry_fallback_due",),
    "post_fill_packet": ("post_fill_packet",),
    "break_even_due": ("break_even_due",),
    "trailing_due": ("trailing_due",),
    "break_even_trailing_due": ("break_even_due", "trailing_due"),
    "time_stop_due": ("time_stop_due",),
    "time_stop_overdue": ("time_stop_overdue",),
}
_H4A_MONITOR_PRICE_KEYS = (
    "execution_price_now",
    "current_execution_price",
    "spread_mid",
    "spread",
    "price_now",
    "future_mid",
    "spot_mid",
)

CANONICAL_SIGNAL_ACTIONS = frozenset(
    {
        "mark_viewed",
        "enter_submitted",
        "enter_filled",
        "entry_cancelled",
        "exit_submitted",
        "exit_filled",
        "confirm_followup",
        "manual_override",
    }
)


def _parse_iso_utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_iso_utc(value: datetime | None) -> str | None:
    if not isinstance(value, datetime):
        return None
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")


def _metric_map(row: Mapping[str, object]) -> Mapping[str, object]:
    metrics = row.get("signal_metrics")
    return metrics if isinstance(metrics, Mapping) else {}


def _has_post_fill_state(row: Mapping[str, object] | None) -> bool:
    row_map: Mapping[str, object] = row if isinstance(row, Mapping) else {}
    status = str(row_map.get("operator_signal_status") or "").strip().lower()
    if status not in {"enter_filled", "manual_override"} and not row_map.get("enter_filled_at"):
        return False
    return bool(
        row_map.get("fill_ts")
        or row_map.get("fill_price")
        or row_map.get("effective_fill_price")
    )


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _to_int(value: object) -> int | None:
    parsed = _to_float(value)
    if parsed is None:
        return None
    return int(round(parsed))


def normalize_signal_action_request(
    value: object,
    *,
    legacy_mode: bool = False,
) -> tuple[str, str] | None:
    raw = str(value or "").strip().lower()
    if raw in {"ack", "acknowledged"}:
        return "mark_viewed", "ack" if legacy_mode else "mark_viewed"
    if raw in {"mark_viewed", "viewed"}:
        return "mark_viewed", "mark_viewed"
    if raw in {"enter_submitted", "submit_enter", "submitted"}:
        return "enter_submitted", "enter_submitted"
    if raw in {"enter_filled", "filled", "fill_enter"}:
        return "enter_filled", "enter_filled"
    if raw in {"entry_cancelled", "cancel_enter", "enter_cancelled"}:
        return "entry_cancelled", "entry_cancelled"
    if raw in {"exit_submitted", "submit_exit"}:
        return "exit_submitted", "exit_submitted"
    if raw in {"exit_filled", "fill_exit"}:
        return "exit_filled", "exit_filled"
    if raw in {"confirm_followup", "followup_confirmed", "confirm_recalc", "confirm_h4a"}:
        return "confirm_followup", "confirm_followup"
    if raw in {"manual_override", "override"}:
        return "manual_override", "manual_override"
    if raw in {"enter", "open"}:
        return "enter_filled", "enter" if legacy_mode else "enter_filled"
    if raw in {"exit", "close"}:
        return "exit_filled", "exit" if legacy_mode else "exit_filled"
    if raw in {"hold", "hold_open"}:
        if legacy_mode:
            return "enter_filled", "enter"
        return "enter_filled", "enter_filled"
    return None


def normalize_execution_action(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"ack", "acknowledged", "mark_viewed", "viewed"}:
        return "mark_viewed"
    if raw in {"enter_submitted", "submit_enter", "submitted"}:
        return "enter_submitted"
    if raw in {"enter", "open", "hold", "hold_open", "enter_filled", "filled", "fill_enter"}:
        return "enter_filled"
    if raw in {"entry_cancelled", "cancel_enter", "enter_cancelled"}:
        return "entry_cancelled"
    if raw in {"exit_submitted", "submit_exit"}:
        return "exit_submitted"
    if raw in {"exit", "close", "exit_filled", "fill_exit"}:
        return "exit_filled"
    if raw in {"confirm_followup", "followup_confirmed", "confirm_recalc", "confirm_h4a"}:
        return "confirm_followup"
    if raw in {"manual_override", "override"}:
        return "manual_override"
    return raw or "enter_filled"


def normalize_legacy_execution_action(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"ack", "acknowledged", "mark_viewed", "viewed"}:
        return "ack"
    if raw in {
        "enter",
        "open",
        "hold",
        "hold_open",
        "enter_submitted",
        "submit_enter",
        "submitted",
        "enter_filled",
        "filled",
        "fill_enter",
    }:
        return "enter"
    if raw in {
        "exit",
        "close",
        "exit_submitted",
        "submit_exit",
        "exit_filled",
        "fill_exit",
    }:
        return "exit"
    if raw in {"entry_cancelled", "cancel_enter", "enter_cancelled"}:
        return "cancel_enter"
    if raw in {"confirm_followup", "followup_confirmed", "confirm_recalc", "confirm_h4a"}:
        return "confirm_followup"
    if raw in {"manual_override", "override"}:
        return "manual_override"
    return raw or "enter"


def is_view_action(value: object) -> bool:
    return normalize_execution_action(value) == "mark_viewed"


def is_enter_fill_action(value: object) -> bool:
    return normalize_execution_action(value) == "enter_filled"


def is_exit_fill_action(value: object) -> bool:
    return normalize_execution_action(value) == "exit_filled"


def normalize_operator_execution_mode(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw == OPERATOR_EXECUTION_MODE_MANUAL_OVERRIDE:
        return OPERATOR_EXECUTION_MODE_MANUAL_OVERRIDE
    return OPERATOR_EXECUTION_MODE_BASELINE


def normalize_same_bar_resolution(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in VALID_SAME_BAR_RESOLUTIONS:
        return raw
    return SAME_BAR_RESOLUTION_LIVE


def normalize_exit_reason_code(value: object) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in H4A_EXIT_REASON_CODES:
        return raw
    return None


def normalize_h4a_followup_stage(value: object) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in H4A_FOLLOWUP_STAGES:
        return raw
    return None


def expand_h4a_followup_stage(value: object) -> tuple[str, ...]:
    stage = normalize_h4a_followup_stage(value)
    if stage is None:
        return ()
    components = _H4A_FOLLOWUP_STAGE_COMPONENTS.get(stage, (stage,))
    expanded: list[str] = [stage]
    for item in components:
        if item not in expanded:
            expanded.append(item)
    return tuple(expanded)


def normalize_h4a_followup_confirmations(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, dict[str, object]] = {}
    for raw_stage, raw_payload in value.items():
        stage = normalize_h4a_followup_stage(raw_stage)
        if stage is None:
            continue
        payload: dict[str, object] = {}
        if isinstance(raw_payload, Mapping):
            confirmed_at = _format_iso_utc(_parse_iso_utc(raw_payload.get("confirmed_at")))
            if confirmed_at is not None:
                payload["confirmed_at"] = confirmed_at
            confirmed_by = str(raw_payload.get("confirmed_by") or "").strip()
            if confirmed_by:
                payload["confirmed_by"] = confirmed_by
            reason_code = str(raw_payload.get("reason_code") or "").strip()
            if reason_code:
                payload["reason_code"] = reason_code
            note = str(raw_payload.get("note") or "").strip()
            if note:
                payload["note"] = note
        else:
            confirmed_at = _format_iso_utc(_parse_iso_utc(raw_payload))
            if confirmed_at is not None:
                payload["confirmed_at"] = confirmed_at
        if not payload:
            payload["confirmed"] = True
        normalized[stage] = payload
    return normalized


def is_h4a_followup_stage_confirmed(
    confirmations: Mapping[str, object] | None,
    *,
    stage: object,
) -> bool:
    normalized_stage = normalize_h4a_followup_stage(stage)
    if normalized_stage is None:
        return False
    confirmation_map = normalize_h4a_followup_confirmations(confirmations)
    if normalized_stage in confirmation_map:
        return True
    if normalized_stage in {"break_even_due", "trailing_due"}:
        return "break_even_trailing_due" in confirmation_map
    if normalized_stage == "break_even_trailing_due":
        return (
            "break_even_trailing_due" in confirmation_map
            or (
                "break_even_due" in confirmation_map
                and "trailing_due" in confirmation_map
            )
        )
    return False


def resolve_signal_expire_ts(row: Mapping[str, object]) -> datetime | None:
    metrics = _metric_map(row)
    entry_plan = row.get("entry_plan")
    entry_plan_map = entry_plan if isinstance(entry_plan, Mapping) else {}
    for container in (row, entry_plan_map, metrics):
        for key in (
            "signal_expire_ts",
            "expire_ts",
            "entry_expire_ts",
            "entry_order_expire_ts",
            "valid_until",
        ):
            parsed = _parse_iso_utc(container.get(key))
            if parsed is not None:
                return parsed
    return None


def build_h4a_execution_contract(
    *,
    settings,
    row: Mapping[str, object] | None = None,
    operator_execution_mode: str | None = None,
) -> dict[str, object]:
    row_map: Mapping[str, object] = row if isinstance(row, Mapping) else {}
    metrics = _metric_map(row_map)
    exec_cfg = settings.signal_engine.morning_plan.execution
    expire_ts = resolve_signal_expire_ts(row_map)
    signal_expire_ts = _format_iso_utc(expire_ts)
    fallback_after = (
        _to_int(metrics.get("stop_limit_fallback_to_market_min"))
        or _to_int(metrics.get("limit_fallback_to_market_minutes"))
        or int(exec_cfg.limit_fallback_to_market_minutes)
    )
    fallback_slip = (
        _to_int(metrics.get("stop_limit_fallback_slip_ticks"))
        or _to_int(metrics.get("limit_fallback_slip_ticks"))
        or int(exec_cfg.limit_fallback_slip_ticks)
    )
    time_stop_minutes = (
        _to_int(metrics.get("time_stop_minutes")) or int(exec_cfg.max_holding_minutes)
    )
    mode = normalize_operator_execution_mode(
        operator_execution_mode
        if operator_execution_mode is not None
        else row_map.get("operator_execution_mode")
    )
    return {
        "baseline_id": ACTIVE_BASELINE_ID,
        "execution_profile_id": ACTIVE_BASELINE_ID,
        "reference_baseline_id": REFERENCE_BASELINE_ID,
        "operator_execution_mode": mode,
        "signal_expire_ts": signal_expire_ts,
        "entry_order_type": "LIMIT",
        "entry_improve_ticks": int(exec_cfg.limit_entry_improve_ticks),
        "entry_fallback_after_minutes": int(fallback_after),
        "entry_fallback_slip_ticks": int(fallback_slip),
        "break_even_rr": float(exec_cfg.break_even_rr),
        "break_even_buffer_ticks": int(exec_cfg.break_even_buffer_ticks),
        "trail_activation_rr": float(exec_cfg.trail_activation_rr),
        "trail_offset_ticks": int(exec_cfg.trail_offset_ticks),
        "time_stop_minutes": int(time_stop_minutes),
        "same_bar_policy": str(exec_cfg.same_bar_policy),
        "same_bar_policy_source": SAME_BAR_POLICY_SOURCE,
        "max_profit_rr": float(exec_cfg.max_profit_rr),
        "tp_rr": float(exec_cfg.tp_rr),
        "sl_rr": float(exec_cfg.sl_rr),
    }


def infer_fill_side_action(
    *,
    row: Mapping[str, object] | None,
    side_action: object,
) -> str:
    raw = str(side_action or "").strip().upper()
    if raw in {"BUY", "SELL"}:
        return raw
    row_map: Mapping[str, object] = row if isinstance(row, Mapping) else {}
    metrics = _metric_map(row_map)
    engine_action = str(metrics.get("engine_action") or row_map.get("engine_action") or "").strip().upper()
    if engine_action in {"BUY", "SELL"}:
        return engine_action
    direction = str(row_map.get("signal_direction") or metrics.get("signal_direction") or "").strip().lower()
    if direction in {"sell", "short", "reverse"}:
        return "SELL"
    return "BUY"


def build_h4a_fill_state(
    *,
    settings,
    row: Mapping[str, object] | None,
    fill_price: object,
    fill_ts: object,
    side_action: object = None,
    tick_size: object = None,
    base_risk_ticks: object = None,
    fallback_applied: bool = False,
    same_bar_resolution: object = None,
    operator_execution_mode: str | None = None,
) -> dict[str, object]:
    row_map: Mapping[str, object] = row if isinstance(row, Mapping) else {}
    metrics = _metric_map(row_map)
    contract = build_h4a_execution_contract(
        settings=settings,
        row=row_map,
        operator_execution_mode=operator_execution_mode,
    )
    fill_price_value = _to_float(fill_price)
    fill_dt = _parse_iso_utc(fill_ts)
    if fill_dt is None:
        fill_dt = datetime.now(timezone.utc)
    time_stop_minutes = int(contract.get("time_stop_minutes") or 0)
    time_stop_deadline = fill_dt + timedelta(minutes=max(time_stop_minutes, 0))
    state: dict[str, object] = {
        "fill_ts": _format_iso_utc(fill_dt),
        "fill_price": fill_price_value,
        "effective_fill_price": fill_price_value,
        "fallback_applied": bool(fallback_applied),
        "recalc_applied": False,
        "time_stop_deadline_ts": _format_iso_utc(time_stop_deadline),
        "time_stop_180m": _format_iso_utc(time_stop_deadline),
        "same_bar_resolution": normalize_same_bar_resolution(same_bar_resolution),
        "initial_loss_sl": None,
        "tp_limit": None,
        "protective_sl": None,
        "break_even_activation_price": None,
        "break_even_stop_price": None,
        "trail_activation_price": None,
        "operator_execution_mode": contract.get("operator_execution_mode"),
    }
    if fill_price_value is None:
        return state

    tick_size_value = _to_float(tick_size)
    if tick_size_value is None:
        tick_size_value = (
            _to_float(metrics.get("tick_size"))
            or _to_float(metrics.get("price_tick"))
            or _to_float(metrics.get("min_price_increment"))
        )
    base_risk_ticks_value = _to_float(base_risk_ticks)
    if base_risk_ticks_value is None:
        base_risk_ticks_value = _to_float(metrics.get("sl_ticks")) or _to_float(metrics.get("risk_ticks"))
    if tick_size_value is None or tick_size_value <= 0 or base_risk_ticks_value is None or base_risk_ticks_value <= 0:
        return state

    side = infer_fill_side_action(row=row_map, side_action=side_action)
    sl_rr = float(contract.get("sl_rr") or 0.0)
    tp_rr = float(contract.get("tp_rr") or 0.0)
    break_even_rr = float(contract.get("break_even_rr") or 0.0)
    break_even_buffer_ticks = int(contract.get("break_even_buffer_ticks") or 0)
    trail_activation_rr = float(contract.get("trail_activation_rr") or 0.0)
    effective_risk_ticks = max(int(round(base_risk_ticks_value * sl_rr)), 1)
    effective_tp_ticks = max(int(round(effective_risk_ticks * tp_rr)), 1)
    break_even_activation_ticks = max(int(round(effective_risk_ticks * break_even_rr)), 0)
    trail_activation_ticks = max(int(round(effective_risk_ticks * trail_activation_rr)), 0)
    risk_distance = float(effective_risk_ticks) * float(tick_size_value)
    tp_distance = float(effective_tp_ticks) * float(tick_size_value)
    break_even_activation_distance = float(break_even_activation_ticks) * float(tick_size_value)
    trail_activation_distance = float(trail_activation_ticks) * float(tick_size_value)
    break_even_buffer_distance = float(break_even_buffer_ticks) * float(tick_size_value)
    if side == "SELL":
        initial_loss_sl = float(fill_price_value + risk_distance)
        tp_limit = float(fill_price_value - tp_distance)
        break_even_activation_price = float(fill_price_value - break_even_activation_distance)
        break_even_stop_price = float(fill_price_value - break_even_buffer_distance)
        trail_activation_price = float(fill_price_value - trail_activation_distance)
    else:
        initial_loss_sl = float(fill_price_value - risk_distance)
        tp_limit = float(fill_price_value + tp_distance)
        break_even_activation_price = float(fill_price_value + break_even_activation_distance)
        break_even_stop_price = float(fill_price_value + break_even_buffer_distance)
        trail_activation_price = float(fill_price_value + trail_activation_distance)

    state.update(
        {
            "recalc_applied": True,
            "side_action": side,
            "tick_size": float(tick_size_value),
            "base_risk_ticks": float(base_risk_ticks_value),
            "effective_risk_ticks": int(effective_risk_ticks),
            "effective_tp_ticks": int(effective_tp_ticks),
            "initial_loss_sl": initial_loss_sl,
            "tp_limit": tp_limit,
            "protective_sl": initial_loss_sl,
            "break_even_activation_price": break_even_activation_price,
            "break_even_stop_price": break_even_stop_price,
            "trail_activation_price": trail_activation_price,
        }
    )
    return state


def resolve_h4a_monitor_price(
    row: Mapping[str, object] | None,
) -> tuple[float | None, str | None]:
    row_map: Mapping[str, object] = row if isinstance(row, Mapping) else {}
    metrics = _metric_map(row_map)
    for key in _H4A_MONITOR_PRICE_KEYS:
        parsed = _to_float(row_map.get(key))
        if parsed is not None:
            return parsed, key
    entry_range = row_map.get("entry_range_now")
    if isinstance(entry_range, Mapping):
        for key in ("price_now", "spread_now", "future_now", "stock_now"):
            parsed = _to_float(entry_range.get(key))
            if parsed is not None:
                return parsed, f"entry_range_now.{key}"
    for key in ("execution_price_now", "spread_mid", "future_mid", "spot_mid"):
        parsed = _to_float(metrics.get(key))
        if parsed is not None:
            return parsed, f"signal_metrics.{key}"
    return None, None


def _trigger_reached(*, current_price: float | None, trigger_price: float | None, side: str) -> bool:
    if current_price is None or trigger_price is None:
        return False
    if side == "SELL":
        return current_price <= trigger_price
    return current_price >= trigger_price


def build_h4a_followup_state(
    *,
    row: Mapping[str, object] | None,
    now_utc: datetime | None = None,
) -> dict[str, object]:
    row_map: Mapping[str, object] = row if isinstance(row, Mapping) else {}
    execution_contract = row_map.get("execution_contract")
    contract = execution_contract if isinstance(execution_contract, Mapping) else {}
    baseline_id = str(
        row_map.get("baseline_id") or contract.get("baseline_id") or ACTIVE_BASELINE_ID
    ).strip().upper()
    if baseline_id != ACTIVE_BASELINE_ID:
        return {}

    now_dt = now_utc if isinstance(now_utc, datetime) else datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    else:
        now_dt = now_dt.astimezone(timezone.utc)

    state: dict[str, object] = {"baseline_id": ACTIVE_BASELINE_ID}
    confirmations = normalize_h4a_followup_confirmations(row_map.get("h4a_followup_confirmations"))
    state["confirmations"] = confirmations
    state["confirmed_stages"] = list(confirmations.keys())
    operator_status = str(row_map.get("operator_signal_status") or "").strip().lower()
    operator_execution_mode = normalize_operator_execution_mode(
        row_map.get("operator_execution_mode") or contract.get("operator_execution_mode")
    )
    required_stages: list[str] = []

    fallback_after_minutes = _to_int(contract.get("entry_fallback_after_minutes")) or 0
    enter_submitted_at = _parse_iso_utc(row_map.get("enter_submitted_at"))
    if (
        fallback_after_minutes > 0
        and operator_status == "enter_submitted"
        and not row_map.get("enter_filled_at")
        and enter_submitted_at is not None
    ):
        fallback_due_at = enter_submitted_at + timedelta(minutes=fallback_after_minutes)
        state["entry_fallback_due_at"] = _format_iso_utc(fallback_due_at)
        state["entry_fallback_due"] = now_dt >= fallback_due_at
        if bool(state.get("entry_fallback_due")):
            required_stages.append("entry_fallback_due")

    if not _has_post_fill_state(row_map):
        unconfirmed = [
            stage
            for stage in required_stages
            if not is_h4a_followup_stage_confirmed(confirmations, stage=stage)
        ]
        if operator_execution_mode == OPERATOR_EXECUTION_MODE_MANUAL_OVERRIDE:
            state["confirmation_required"] = False
            state["unconfirmed_stages"] = []
            state["baseline_guard_status"] = "manual_override"
            state["baseline_guard_reasons"] = []
        else:
            state["confirmation_required"] = bool(unconfirmed)
            state["unconfirmed_stages"] = unconfirmed
            state["baseline_guard_status"] = "confirmation_required" if unconfirmed else "ok"
            state["baseline_guard_reasons"] = list(unconfirmed)
        return state

    current_price, current_price_source = resolve_h4a_monitor_price(row_map)
    side = str(row_map.get("side_action") or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        side = infer_fill_side_action(row=row_map, side_action=None)
    break_even_activation_price = _to_float(row_map.get("break_even_activation_price"))
    trail_activation_price = _to_float(row_map.get("trail_activation_price"))
    deadline = _parse_iso_utc(row_map.get("time_stop_deadline_ts"))
    reminder_due = False
    overdue = False
    if deadline is not None:
        reminder_due_at = deadline - timedelta(minutes=H4A_FOLLOWUP_TIME_STOP_REMINDER_LEAD_MINUTES)
        reminder_due = reminder_due_at <= now_dt < deadline
        overdue = now_dt >= deadline
        state["time_stop_reminder_due_at"] = _format_iso_utc(reminder_due_at)
        state["time_stop_deadline_ts"] = _format_iso_utc(deadline)
    state.update(
        {
            "post_fill_active": True,
            "current_price": current_price,
            "current_price_source": current_price_source,
            "break_even_trigger_reached": _trigger_reached(
                current_price=current_price,
                trigger_price=break_even_activation_price,
                side=side,
            ),
            "trail_trigger_reached": _trigger_reached(
                current_price=current_price,
                trigger_price=trail_activation_price,
                side=side,
            ),
            "time_stop_reminder_due": reminder_due,
            "time_stop_overdue": overdue,
        }
    )
    required_stages.append("post_fill_packet")
    if bool(state.get("break_even_trigger_reached")):
        required_stages.append("break_even_due")
    if bool(state.get("trail_trigger_reached")):
        required_stages.append("trailing_due")
    if bool(state.get("time_stop_reminder_due")):
        required_stages.append("time_stop_due")
    if bool(state.get("time_stop_overdue")):
        required_stages.append("time_stop_overdue")
    unconfirmed = [
        stage
        for stage in required_stages
        if not is_h4a_followup_stage_confirmed(confirmations, stage=stage)
    ]
    if operator_execution_mode == OPERATOR_EXECUTION_MODE_MANUAL_OVERRIDE:
        state["confirmation_required"] = False
        state["unconfirmed_stages"] = []
        state["baseline_guard_status"] = "manual_override"
        state["baseline_guard_reasons"] = []
    else:
        state["confirmation_required"] = bool(unconfirmed)
        state["unconfirmed_stages"] = unconfirmed
        if "time_stop_overdue" in unconfirmed:
            state["baseline_guard_status"] = "deviation_review"
        elif unconfirmed:
            state["baseline_guard_status"] = "confirmation_required"
        else:
            state["baseline_guard_status"] = "ok"
        state["baseline_guard_reasons"] = list(unconfirmed)
    return state
