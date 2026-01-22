from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EventFilterResult:
    allowed: bool
    reasons: list[str]


def apply_event_filters(
    days_to_expiry: int,
    days_to_exdiv: int,
    min_days_to_expiry: int,
    min_days_to_exdiv: int,
) -> EventFilterResult:
    reasons: list[str] = []
    if days_to_expiry < min_days_to_expiry:
        reasons.append("expiry_too_close")
    if days_to_exdiv < min_days_to_exdiv:
        reasons.append("exdiv_too_close")
    return EventFilterResult(allowed=not reasons, reasons=reasons)
