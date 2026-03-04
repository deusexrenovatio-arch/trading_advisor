from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from moex_carry.domain.decision import NewsItem


SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass
class NewsGateResult:
    action: str
    highest_severity: str
    matched_items: list[NewsItem]
    errors: list[str]


def _severity_value(severity: str) -> int:
    return SEVERITY_ORDER.get(severity, -1)


def apply_news_filter(
    news_items: Iterable[NewsItem],
    lookback_minutes: int,
    block_severity_threshold: str,
    reduce_severity_threshold: str,
    as_of_utc: datetime | None = None,
    allowed_sources: Iterable[str] | None = None,
    enforce_source_allowlist: bool = False,
) -> NewsGateResult:
    errors: list[str] = []
    block_value = _severity_value(block_severity_threshold)
    reduce_value = _severity_value(reduce_severity_threshold)
    if block_value <= reduce_value:
        errors.append("invalid_severity_thresholds")

    as_of = as_of_utc if as_of_utc is not None else datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    else:
        as_of = as_of.astimezone(timezone.utc)
    lookback_cutoff = as_of - timedelta(minutes=lookback_minutes)
    normalized_sources = {
        str(source).strip().lower() for source in (allowed_sources or []) if str(source).strip()
    }
    matched: list[NewsItem] = []
    highest = "low"

    for item in news_items:
        if (
            enforce_source_allowlist
            and normalized_sources
            and str(item.source).strip().lower() not in normalized_sources
        ):
            continue
        severity_value = _severity_value(item.severity)
        if severity_value < 0:
            errors.append(f"invalid_severity:{item.item_id}")
            continue
        if not (0.0 <= item.impact_score <= 1.0):
            errors.append(f"invalid_impact_score:{item.item_id}")
            continue
        timestamp = item.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        if timestamp < lookback_cutoff:
            continue
        matched.append(item)
        if _severity_value(highest) < severity_value:
            highest = item.severity

    if errors:
        return NewsGateResult(action="block", highest_severity=highest, matched_items=matched, errors=errors)

    if any(_severity_value(item.severity) >= block_value for item in matched):
        return NewsGateResult(action="block", highest_severity=highest, matched_items=matched, errors=[])
    if any(_severity_value(item.severity) >= reduce_value for item in matched):
        return NewsGateResult(action="reduce", highest_severity=highest, matched_items=matched, errors=[])
    return NewsGateResult(action="allow", highest_severity=highest, matched_items=matched, errors=[])
