from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PretradeDirection = Literal["cash_and_carry", "reverse"]
PretradeStatus = Literal["pass", "block", "check"]


@dataclass(frozen=True)
class PretradeRuntimeParams:
    snapshots: int
    min_hits: int
    eps: float
    sync_sec: float
    poll_sec: float
    qty_fut: float
    participation_rate: float
    future_scale: float


def normalize_pretrade_direction(
    value: object, *, default: PretradeDirection = "cash_and_carry"
) -> PretradeDirection | None:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    if normalized in {"cash_and_carry", "reverse"}:
        return normalized  # type: ignore[return-value]
    return None


def classify_pretrade_status(result: dict[str, object]) -> PretradeStatus:
    ready_to_place = bool(result.get("ready_to_place"))
    status = str(result.get("status") or "").strip().lower()
    if ready_to_place or status in {"place", "ready", "pass"}:
        return "pass"
    if status in {"check", "pending", "unknown"}:
        return "check"
    return "block"


def enrich_pretrade_result(
    result: dict[str, object], *, params: PretradeRuntimeParams
) -> dict[str, object]:
    enriched = dict(result)
    enriched["params"] = {
        "snapshots": params.snapshots,
        "min_hits": params.min_hits,
        "eps": params.eps,
        "sync_sec": params.sync_sec,
        "poll_sec": params.poll_sec,
        "qty_fut": params.qty_fut,
        "participation_rate": params.participation_rate,
        "future_scale": params.future_scale,
    }
    enriched["pretrade_status"] = classify_pretrade_status(enriched)
    return enriched
