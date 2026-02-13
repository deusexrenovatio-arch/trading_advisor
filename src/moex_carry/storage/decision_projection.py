from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable


PROJECTION_PARITY_FIELDS: tuple[str, ...] = (
    "decision_id",
    "created_at",
    "strategy_type",
    "primary_instrument",
    "action",
    "risk_state",
    "news_severity",
)


def normalize_projection_value(field: str, value: object) -> object:
    if field == "created_at":
        return _normalize_datetime(value)
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


def latest_projection_rows(rows: Iterable[dict[str, object]]) -> dict[str, dict[str, object]]:
    latest: dict[str, dict[str, object]] = {}
    for row in rows:
        decision_id = str(row.get("decision_id") or "").strip()
        if not decision_id:
            continue
        latest[decision_id] = row
    return latest


def compute_projection_parity(
    jsonl_rows: Iterable[dict[str, object]],
    db_rows: Iterable[dict[str, object]],
    *,
    fields: Iterable[str] = PROJECTION_PARITY_FIELDS,
    sample_mismatches: int = 20,
) -> dict[str, object]:
    field_list = tuple(fields)
    json_map = latest_projection_rows(jsonl_rows)
    db_map = latest_projection_rows(db_rows)
    total = len(json_map)
    matched = 0
    mismatches: list[dict[str, object]] = []

    for decision_id, source_row in json_map.items():
        target_row = db_map.get(decision_id)
        if target_row is None:
            if len(mismatches) < sample_mismatches:
                mismatches.append(
                    {
                        "decision_id": decision_id,
                        "reason": "missing_in_db",
                    }
                )
            continue

        diff_fields: list[str] = []
        for field in field_list:
            source_value = normalize_projection_value(field, source_row.get(field))
            target_value = normalize_projection_value(field, target_row.get(field))
            if source_value != target_value:
                diff_fields.append(field)
        if diff_fields:
            if len(mismatches) < sample_mismatches:
                mismatches.append(
                    {
                        "decision_id": decision_id,
                        "reason": "field_mismatch",
                        "fields": diff_fields,
                    }
                )
            continue
        matched += 1

    parity_ratio = 1.0 if total == 0 else matched / total
    extra_in_db = sorted(set(db_map).difference(set(json_map)))
    extra_in_db_sample = extra_in_db[:sample_mismatches]

    return {
        "total_source_rows": total,
        "db_rows": len(db_map),
        "matched_rows": matched,
        "parity_ratio": parity_ratio,
        "missing_in_db": sum(1 for item in mismatches if item.get("reason") == "missing_in_db"),
        "field_mismatches": sum(1 for item in mismatches if item.get("reason") == "field_mismatch"),
        "extra_in_db": len(extra_in_db),
        "mismatches_sample": mismatches,
        "extra_in_db_sample": extra_in_db_sample,
    }


def _normalize_datetime(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None).isoformat() + "Z"
