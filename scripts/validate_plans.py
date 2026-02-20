from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ITEM_ID_PATTERN = re.compile(r"^[A-Z0-9-]+$")
ALLOWED_STATUSES = {"planned", "active", "blocked", "completed", "deferred"}
ALLOWED_EXECUTION_MODES = {"autonomous", "assisted", "manual"}


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("plans file must be a YAML object")
    return payload


def _parse_iso_date(value: str, field: str, item_id: str, errors: list[str]) -> None:
    try:
        date.fromisoformat(value)
    except ValueError:
        errors.append(f"{item_id}: invalid ISO date in '{field}': {value}")


def _required_non_empty_str(
    row: dict[str, Any],
    field: str,
    item_id: str,
    errors: list[str],
) -> str:
    value = str(row.get(field, "")).strip()
    if not value:
        errors.append(f"{item_id}: missing required field '{field}'")
    return value


def _required_list(
    row: dict[str, Any],
    field: str,
    item_id: str,
    errors: list[str],
) -> list[str]:
    raw = row.get(field)
    if not isinstance(raw, list) or not raw:
        errors.append(f"{item_id}: missing non-empty list '{field}'")
        return []
    out = [str(x).strip() for x in raw if str(x).strip()]
    if not out:
        errors.append(f"{item_id}: list '{field}' has no valid values")
    return out


def run(path: Path) -> int:
    if not path.exists():
        print(f"plans file not found: {path.as_posix()}")
        return 1

    try:
        payload = _load_yaml(path)
    except Exception as exc:
        print(f"plans validation failed: invalid YAML ({exc})")
        return 1

    errors: list[str] = []
    version = payload.get("version")
    if version != 1:
        errors.append(f"unsupported version: {version!r} (expected 1)")

    updated_at = str(payload.get("updated_at", "")).strip()
    if not updated_at:
        errors.append("missing top-level field 'updated_at'")
    else:
        _parse_iso_date(updated_at, "updated_at", "plans", errors)

    items_raw = payload.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        errors.append("missing non-empty top-level list 'items'")
        items_raw = []

    ids: set[str] = set()
    status_counts: Counter[str] = Counter()
    lane_active_counts: defaultdict[str, int] = defaultdict(int)
    dependencies_by_id: dict[str, list[str]] = {}

    for idx, raw in enumerate(items_raw):
        if not isinstance(raw, dict):
            errors.append(f"items[{idx}] must be an object")
            continue

        item_id = _required_non_empty_str(raw, "id", f"items[{idx}]", errors)
        if item_id:
            if item_id in ids:
                errors.append(f"duplicate item id: {item_id}")
            ids.add(item_id)
            if not ITEM_ID_PATTERN.match(item_id):
                errors.append(f"{item_id}: invalid id format (allowed: A-Z, 0-9, '-')")

        _required_non_empty_str(raw, "title", item_id or f"items[{idx}]", errors)
        lane = _required_non_empty_str(raw, "lane", item_id or f"items[{idx}]", errors)
        status = _required_non_empty_str(raw, "status", item_id or f"items[{idx}]", errors)
        execution_mode = _required_non_empty_str(
            raw,
            "execution_mode",
            item_id or f"items[{idx}]",
            errors,
        )
        _required_non_empty_str(raw, "owner", item_id or f"items[{idx}]", errors)
        _required_list(raw, "acceptance", item_id or f"items[{idx}]", errors)
        _required_list(raw, "checks", item_id or f"items[{idx}]", errors)

        if status and status not in ALLOWED_STATUSES:
            errors.append(
                f"{item_id}: invalid status '{status}' (allowed: {sorted(ALLOWED_STATUSES)})"
            )
        if execution_mode and execution_mode not in ALLOWED_EXECUTION_MODES:
            errors.append(
                f"{item_id}: invalid execution_mode '{execution_mode}' "
                f"(allowed: {sorted(ALLOWED_EXECUTION_MODES)})"
            )

        if status:
            status_counts[status] += 1
        if lane and status == "active":
            lane_active_counts[lane] += 1

        dependencies = raw.get("dependencies") or []
        if not isinstance(dependencies, list):
            errors.append(f"{item_id}: field 'dependencies' must be a list when present")
            dependencies = []
        dependencies_by_id[item_id] = [str(dep).strip() for dep in dependencies if str(dep).strip()]

        for field in ("started_at", "completed_at"):
            if field in raw:
                value = str(raw.get(field, "")).strip()
                if not value:
                    errors.append(f"{item_id}: field '{field}' must not be empty")
                else:
                    _parse_iso_date(value, field, item_id, errors)

        if status == "completed" and "completed_at" not in raw:
            errors.append(f"{item_id}: completed item must include 'completed_at'")

    for item_id, deps in dependencies_by_id.items():
        for dep in deps:
            if dep not in ids:
                errors.append(f"{item_id}: unknown dependency '{dep}'")

    overloaded_lanes = sorted([lane for lane, count in lane_active_counts.items() if count > 1])
    if overloaded_lanes:
        errors.append(
            "more than one active item per lane is not allowed: "
            + ", ".join(overloaded_lanes)
        )

    if errors:
        print("plans validation failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    ordered_status_counts = ", ".join(
        f"{name}={status_counts.get(name, 0)}"
        for name in ("active", "planned", "blocked", "deferred", "completed")
    )
    print(
        "plans validation: OK "
        f"(items={len(ids)} updated_at={updated_at} statuses[{ordered_status_counts}])"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate machine-readable plan registry.")
    parser.add_argument("--path", default="plans/PLANS.yaml")
    args = parser.parse_args()
    sys.exit(run(Path(args.path)))


if __name__ == "__main__":
    main()
