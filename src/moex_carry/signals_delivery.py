from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Mapping


DELIVERY_ACTIONS = frozenset({"enter", "exit", "hold_open"})

_ENTRY_PLAN_KEYS = (
    "entry_stock_min",
    "entry_stock_max",
    "entry_future_min_per_share",
    "entry_future_max_per_share",
    "entry_spread_min",
    "entry_spread_max",
    "entry_spread_pct_min",
    "entry_spread_pct_max",
)


def parse_iso_utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def first_numeric(record: Mapping[str, object], *keys: str) -> float | None:
    for key in keys:
        if key not in record:
            continue
        parsed = to_float(record.get(key))
        if parsed is not None:
            return parsed
    return None


def bounded_value_ok(*, current: float | None, lower: object, upper: object) -> bool:
    lower_value = to_float(lower)
    upper_value = to_float(upper)
    if lower_value is None and upper_value is None:
        return True
    if current is None:
        return False
    if lower_value is not None and upper_value is not None and lower_value > upper_value:
        lower_value, upper_value = upper_value, lower_value
    if lower_value is not None and current < lower_value:
        return False
    if upper_value is not None and current > upper_value:
        return False
    return True


def signal_action_for_delivery(row: Mapping[str, object]) -> str:
    effective = str(row.get("signal_action_effective") or "").strip().lower()
    if effective:
        return effective
    return str(row.get("signal_action") or "").strip().lower()


def entry_plan_from_row(row: Mapping[str, object]) -> dict[str, float | None]:
    metrics = row.get("signal_metrics")
    metric_map = metrics if isinstance(metrics, Mapping) else {}
    plan: dict[str, float | None] = {}
    for key in _ENTRY_PLAN_KEYS:
        parsed = to_float(row.get(key))
        if parsed is None:
            parsed = to_float(metric_map.get(key))
        plan[key] = parsed
    return plan


def entry_plan_has_bounds(plan: Mapping[str, float | None]) -> bool:
    return any(plan.get(key) is not None for key in _ENTRY_PLAN_KEYS)


def _first_numeric_with_metrics(row: Mapping[str, object], *keys: str) -> float | None:
    direct = first_numeric(row, *keys)
    if direct is not None:
        return direct
    metrics = row.get("signal_metrics")
    if isinstance(metrics, Mapping):
        return first_numeric(metrics, *keys)
    return None


def entry_range_eligible_for_plan(
    row: Mapping[str, object],
    plan: Mapping[str, float | None],
) -> bool:
    if not entry_plan_has_bounds(plan):
        return True
    stock_now = _first_numeric_with_metrics(
        row,
        "spot_mid",
        "spot",
        "stock_mid",
        "stock_price",
        "stock_last_price",
    )
    future_now = _first_numeric_with_metrics(
        row,
        "future_mid",
        "future_price",
        "future_last_price",
    )
    spread_now = _first_numeric_with_metrics(row, "spread_mid", "spread")
    spread_pct_now = _first_numeric_with_metrics(row, "spread_pct")

    if not bounded_value_ok(
        current=stock_now,
        lower=plan.get("entry_stock_min"),
        upper=plan.get("entry_stock_max"),
    ):
        return False
    if not bounded_value_ok(
        current=future_now,
        lower=plan.get("entry_future_min_per_share"),
        upper=plan.get("entry_future_max_per_share"),
    ):
        return False
    if not bounded_value_ok(
        current=spread_now,
        lower=plan.get("entry_spread_min"),
        upper=plan.get("entry_spread_max"),
    ):
        return False
    if not bounded_value_ok(
        current=spread_pct_now,
        lower=plan.get("entry_spread_pct_min"),
        upper=plan.get("entry_spread_pct_max"),
    ):
        return False
    return True


def is_entry_signal_expired(
    row: Mapping[str, object],
    *,
    callback_ttl_hours: int,
    now_utc: datetime | None = None,
) -> bool:
    signal_ts = parse_iso_utc(row.get("timestamp"))
    if signal_ts is None:
        return True
    now_value = now_utc if isinstance(now_utc, datetime) else datetime.now(timezone.utc)
    ttl_hours = max(int(callback_ttl_hours or 0), 1)
    return now_value > (signal_ts + timedelta(hours=ttl_hours))


def signal_delivery_state(
    row: Mapping[str, object],
    *,
    callback_ttl_hours: int,
    now_utc: datetime | None = None,
) -> dict[str, object]:
    action = signal_action_for_delivery(row)
    action_supported = action in DELIVERY_ACTIONS
    signal_used = bool(row.get("signal_used"))
    entry_plan = entry_plan_from_row(row)
    entry_range_eligible = True
    entry_signal_expired = False
    suppressed_reason: str | None = None
    if not action_supported:
        suppressed_reason = "unsupported_action"
    elif action == "enter":
        entry_signal_expired = is_entry_signal_expired(
            row,
            callback_ttl_hours=callback_ttl_hours,
            now_utc=now_utc,
        )
        entry_range_eligible = entry_range_eligible_for_plan(row, entry_plan)
        if signal_used:
            suppressed_reason = "signal_used"
        elif entry_signal_expired:
            suppressed_reason = "entry_expired"
        elif not entry_range_eligible:
            suppressed_reason = "entry_out_of_range"
    return {
        "delivery_action": action,
        "delivery_action_supported": action_supported,
        "delivery_allowed": suppressed_reason is None,
        "delivery_suppressed_reason": suppressed_reason,
        "signal_used": signal_used,
        "entry_signal_expired": entry_signal_expired,
        "entry_range_eligible": entry_range_eligible,
        "entry_plan": entry_plan,
    }
