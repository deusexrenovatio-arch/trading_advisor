from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping


_FAIL_CLOSED_OVERRIDE_SOURCES = {"system", "telegram"}


@dataclass(frozen=True)
class FailClosedResult:
    status: str
    reason_code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class AutoUnwindCandidate:
    stock: str
    future: str
    direction: str | None
    last_execution_at: str
    age_sec: int
    open_leg_total: int
    open_stock_legs: int
    open_future_legs: int


def evaluate_fail_closed_entry(
    *,
    enabled: bool,
    requested_action: str,
    signal_row: Mapping[str, object] | None,
    source: str,
    override: bool,
    override_reason: str | None,
    pretrade_status: object | None = None,
    pretrade_degraded: bool | None = None,
) -> FailClosedResult:
    if not enabled or requested_action != "enter":
        return FailClosedResult(status="pass")

    status_norm = _normalize_pretrade_status(pretrade_status)
    if status_norm is None and signal_row is not None:
        status_norm = _normalize_pretrade_status(_extract_pretrade_status(signal_row))
    degraded = (
        pretrade_degraded
        if isinstance(pretrade_degraded, bool)
        else _extract_pretrade_degraded(signal_row) if signal_row is not None else False
    )

    block_code: str | None = None
    block_message: str | None = None
    if degraded:
        block_code = "ISS_DEGRADED_FAIL_CLOSED"
        block_message = "ISS transport is degraded; entry is blocked by fail-closed policy."
    elif status_norm == "block":
        block_code = "PRETRADE_BLOCKED"
        block_message = "Pretrade gate blocked entry."
    elif status_norm != "pass":
        if signal_row is None:
            block_code = "SIGNAL_CONTEXT_MISSING"
            block_message = "Active signal context is required for entry in fail-closed mode."
        else:
            block_code = "PRETRADE_NOT_CONFIRMED"
            block_message = "Pretrade status is not confirmed for entry."

    if block_code is None:
        return FailClosedResult(status="pass")
    if not override:
        return FailClosedResult(status="block", reason_code=block_code, message=block_message)

    if source not in _FAIL_CLOSED_OVERRIDE_SOURCES:
        return FailClosedResult(
            status="block",
            reason_code="FAIL_CLOSED_OVERRIDE_SOURCE_FORBIDDEN",
            message="Override is allowed only for system or telegram sources.",
        )
    if not (override_reason or "").strip():
        return FailClosedResult(
            status="block",
            reason_code="FAIL_CLOSED_OVERRIDE_REASON_REQUIRED",
            message="Override reason is required in fail-closed mode.",
        )
    return FailClosedResult(
        status="override",
        reason_code=block_code,
        message="Fail-closed block overridden by privileged source.",
    )


def select_auto_unwind_candidates(
    rows: list[Mapping[str, object]],
    *,
    timeout_sec: int,
    now_utc: datetime | None = None,
) -> list[AutoUnwindCandidate]:
    now = now_utc or datetime.now(timezone.utc)
    if timeout_sec < 0:
        timeout_sec = 0
    candidates: list[AutoUnwindCandidate] = []
    for row in rows:
        stock = str(row.get("stock") or "").strip()
        future = str(row.get("future") or "").strip()
        if not stock or not future:
            continue
        if not _coerce_bool(row.get("position_open")):
            continue
        if not _coerce_bool(row.get("position_leg_imbalance")):
            continue
        last_execution_at = _parse_dt(
            row.get("position_last_execution_at")
            or row.get("last_execution_at")
            or row.get("timestamp")
        )
        if last_execution_at is None:
            continue
        age_sec = int(max((now - last_execution_at).total_seconds(), 0))
        if age_sec < timeout_sec:
            continue
        candidates.append(
            AutoUnwindCandidate(
                stock=stock,
                future=future,
                direction=_str_or_none(row.get("signal_direction")),
                last_execution_at=last_execution_at.isoformat().replace("+00:00", "Z"),
                age_sec=age_sec,
                open_leg_total=int(row.get("position_open_leg_total") or 0),
                open_stock_legs=int(row.get("position_open_stock_legs") or 0),
                open_future_legs=int(row.get("position_open_future_legs") or 0),
            )
        )
    candidates.sort(key=lambda item: item.age_sec, reverse=True)
    return candidates


def _extract_pretrade_status(signal_row: Mapping[str, object]) -> object | None:
    if "pretrade_status" in signal_row:
        return signal_row.get("pretrade_status")
    metrics = signal_row.get("signal_metrics")
    if isinstance(metrics, Mapping):
        return metrics.get("pretrade_status")
    return None


def _extract_pretrade_degraded(signal_row: Mapping[str, object]) -> bool:
    raw = signal_row.get("pretrade_degraded")
    parsed = _coerce_optional_bool(raw)
    if parsed is not None:
        return parsed
    metrics = signal_row.get("signal_metrics")
    if isinstance(metrics, Mapping):
        metric_value = _coerce_optional_bool(metrics.get("pretrade_degraded"))
        if metric_value is not None:
            return metric_value
        reasons = metrics.get("advisory_reasons")
        if isinstance(reasons, list):
            for reason in reasons:
                if str(reason).strip().lower() == "iss_transport_error":
                    return True
    return False


def _normalize_pretrade_status(value: object | None) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in {"pass", "place", "ready"}:
        return "pass"
    if raw in {"block", "hold"}:
        return "block"
    if raw in {"check", "pending", "unknown"}:
        return "check"
    return None


def _coerce_bool(value: object) -> bool:
    parsed = _coerce_optional_bool(value)
    return bool(parsed)


def _coerce_optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n"}:
            return False
    return None


def _parse_dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _str_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
