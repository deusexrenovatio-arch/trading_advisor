from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML object in {path.as_posix()}")
    return payload


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=False, sort_keys=False),
        encoding="utf-8",
    )


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in item.items():
        if isinstance(value, str):
            normalized[key] = value
        else:
            normalized[key] = value
    return normalized


def _resolve_index_item_path(index_path: Path, item_path: str) -> Path:
    candidate = Path(item_path)
    if candidate.is_absolute():
        return candidate
    # Prefer repository-root-relative paths produced by this script.
    repo_root = index_path.parent.parent.parent
    search_roots = (
        repo_root,
        index_path.parent.parent,
        index_path.parent,
    )
    for root in search_roots:
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    return (repo_root / candidate).resolve()


def _load_items_from_index(index_path: Path) -> list[dict[str, Any]]:
    payload = _load_yaml(index_path)
    rows = payload.get("items")
    if not isinstance(rows, list):
        return []
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_path = row.get("path")
        if not isinstance(item_path, str) or not item_path.strip():
            continue
        candidate = _resolve_index_item_path(index_path, item_path)
        if not candidate.exists():
            continue
        item = _load_yaml(candidate)
        if isinstance(item, dict) and item:
            items.append(item)
    return items


def _write_items_with_index(
    *,
    items: list[dict[str, Any]],
    root_dir: Path,
    index_path: Path,
    file_prefix: str = "",
) -> None:
    repo_root = Path.cwd().resolve()
    seen: set[str] = set()
    index_rows: list[dict[str, str]] = []
    for item in items:
        item_id = str(item.get("id", "")).strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        filename = f"{file_prefix}{item_id}.yaml" if file_prefix else f"{item_id}.yaml"
        item_path = (root_dir / filename).resolve()
        _write_yaml(item_path, _normalize_item(item))
        try:
            relative_path = item_path.relative_to(repo_root).as_posix()
        except ValueError:
            relative_path = item_path.as_posix()
        index_rows.append(
            {
                "id": item_id,
                "path": relative_path,
            }
        )

    _write_yaml(
        index_path,
        {
            "version": 1,
            "updated_at": date.today().isoformat(),
            "items": index_rows,
        },
    )


def _merge_items(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in (primary, secondary):
        for item in source:
            item_id = str(item.get("id", "")).strip()
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            out.append(item)
    return out


def sync_plans(*, aggregate_path: Path, items_dir: Path, index_path: Path) -> tuple[int, bool]:
    aggregate = _load_yaml(aggregate_path)
    aggregate_items = [row for row in aggregate.get("items", []) if isinstance(row, dict)]
    layout_items = _load_items_from_index(index_path)
    canonical_items = _merge_items(layout_items, aggregate_items) if layout_items else aggregate_items
    if not canonical_items:
        canonical_items = layout_items

    _write_items_with_index(items=canonical_items, root_dir=items_dir, index_path=index_path)
    _write_yaml(
        aggregate_path,
        {
            "version": 1,
            "updated_at": date.today().isoformat(),
            "items": canonical_items,
        },
    )
    return len(canonical_items), bool(layout_items)


def sync_memory(
    *,
    aggregate_path: Path,
    memory_root: Path,
) -> tuple[int, bool]:
    aggregate = _load_yaml(aggregate_path)
    layout_exists = False
    total_entries = 0
    sections = ("decisions", "incidents", "patterns")
    canonical: dict[str, list[dict[str, Any]]] = {name: [] for name in sections}

    for section in sections:
        section_dir = memory_root / section
        index_path = section_dir / "index.yaml"
        layout_rows = _load_items_from_index(index_path)
        if layout_rows:
            layout_exists = True
        aggregate_rows = [
            row for row in aggregate.get(section, []) if isinstance(row, dict)
        ]
        merged = _merge_items(layout_rows, aggregate_rows) if layout_rows else aggregate_rows
        canonical[section] = merged
        total_entries += len(merged)
        _write_items_with_index(
            items=merged,
            root_dir=section_dir,
            index_path=index_path,
        )

    _write_yaml(
        aggregate_path,
        {
            "version": 1,
            "updated_at": date.today().isoformat(),
            "decisions": canonical["decisions"],
            "incidents": canonical["incidents"],
            "patterns": canonical["patterns"],
        },
    )
    return total_entries, layout_exists


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync file-per-item state layout with compatibility aggregates.")
    parser.add_argument("--plans-aggregate", default="plans/PLANS.yaml")
    parser.add_argument("--plans-items-dir", default="plans/items")
    parser.add_argument("--plans-index", default="plans/items/index.yaml")
    parser.add_argument("--memory-aggregate", default="memory/agent_memory.yaml")
    parser.add_argument("--memory-root", default="memory")
    args = parser.parse_args()

    plans_count, plans_layout_exists = sync_plans(
        aggregate_path=Path(args.plans_aggregate),
        items_dir=Path(args.plans_items_dir),
        index_path=Path(args.plans_index),
    )
    memory_count, memory_layout_exists = sync_memory(
        aggregate_path=Path(args.memory_aggregate),
        memory_root=Path(args.memory_root),
    )

    print(
        "state layout sync: OK "
        f"(plans_items={plans_count} plans_layout_exists={plans_layout_exists} "
        f"memory_entries={memory_count} memory_layout_exists={memory_layout_exists})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
