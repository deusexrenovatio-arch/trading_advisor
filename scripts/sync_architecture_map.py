from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Architecture map source must be a JSON object: {path}")
    return payload


def _render_js(payload: dict[str, Any]) -> str:
    json_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"window.ARCH_MAP_DATA = {json_payload};\n"


def _validate_payload(payload: dict[str, Any], root: Path) -> list[str]:
    errors: list[str] = []

    required_top_level = ["title", "subtitle", "generated_from", "nodes", "links"]
    for key in required_top_level:
        if key not in payload:
            errors.append(f"Missing top-level key: {key}")

    nodes = payload.get("nodes")
    links = payload.get("links")
    generated_from = payload.get("generated_from")
    if not isinstance(nodes, list):
        errors.append("'nodes' must be an array")
        nodes = []
    if not isinstance(links, list):
        errors.append("'links' must be an array")
        links = []
    if not isinstance(generated_from, list):
        errors.append("'generated_from' must be an array")
        generated_from = []

    node_ids: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{index}] must be an object")
            continue
        for key in ("id", "label", "kind"):
            if key not in node:
                errors.append(f"nodes[{index}] missing '{key}'")
        node_id = node.get("id")
        if isinstance(node_id, str):
            if node_id in node_ids:
                errors.append(f"Duplicate node id: {node_id}")
            node_ids.add(node_id)
        else:
            errors.append(f"nodes[{index}].id must be a string")

    link_keys: set[tuple[str, str, str]] = set()
    for index, link in enumerate(links):
        if not isinstance(link, dict):
            errors.append(f"links[{index}] must be an object")
            continue
        for key in ("source", "target", "type"):
            if key not in link:
                errors.append(f"links[{index}] missing '{key}'")
        source = link.get("source")
        target = link.get("target")
        link_type = link.get("type")
        if not isinstance(source, str):
            errors.append(f"links[{index}].source must be a string")
            continue
        if not isinstance(target, str):
            errors.append(f"links[{index}].target must be a string")
            continue
        if not isinstance(link_type, str):
            errors.append(f"links[{index}].type must be a string")
            continue
        if source not in node_ids:
            errors.append(f"links[{index}] has unknown source node '{source}'")
        if target not in node_ids:
            errors.append(f"links[{index}] has unknown target node '{target}'")

        identity = (source, target, link_type)
        if identity in link_keys:
            errors.append(f"Duplicate link: {source} -> {target} ({link_type})")
        link_keys.add(identity)

    for index, raw_path in enumerate(generated_from):
        if not isinstance(raw_path, str):
            errors.append(f"generated_from[{index}] must be a string")
            continue
        source_path = root / raw_path
        if not source_path.exists():
            errors.append(
                "generated_from path does not exist: "
                f"{raw_path} (resolved to {source_path})"
            )

    return errors


def _print_summary(payload: dict[str, Any]) -> None:
    nodes = payload.get("nodes", [])
    links = payload.get("links", [])
    kind_counts: dict[str, int] = {}
    for node in nodes:
        if isinstance(node, dict):
            kind = node.get("kind", "unknown")
            if isinstance(kind, str):
                kind_counts[kind] = kind_counts.get(kind, 0) + 1
    kinds_repr = ", ".join(
        f"{kind}={count}" for kind, count in sorted(kind_counts.items(), key=lambda item: item[0])
    )
    print(f"Architecture map summary: nodes={len(nodes)} links={len(links)} kinds[{kinds_repr}]")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync docs/architecture/architecture-map-data.js from JSON source."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("docs/architecture/architecture-map-data.json"),
        help="Path to source JSON file",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("docs/architecture/architecture-map-data.js"),
        help="Path to generated JS file",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write files; fail if target is out of sync.",
    )
    args = parser.parse_args()

    root = _repo_root()
    source_path = (root / args.source).resolve()
    target_path = (root / args.target).resolve()

    if not source_path.exists():
        print(f"ERROR: Source file not found: {source_path}", file=sys.stderr)
        return 2

    payload = _load_json(source_path)
    errors = _validate_payload(payload, root)
    if errors:
        print("ERROR: Architecture map source validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 2

    expected_js = _render_js(payload)
    current_js = target_path.read_text(encoding="utf-8") if target_path.exists() else None

    if args.check:
        if current_js != expected_js:
            rel_target = target_path.relative_to(root)
            print(
                "ERROR: Architecture map is out of sync. "
                f"Run: python scripts/sync_architecture_map.py --source {args.source} --target {args.target}",
                file=sys.stderr,
            )
            print(f"Expected target: {rel_target}", file=sys.stderr)
            return 1
        _print_summary(payload)
        print("Architecture map check: OK")
        return 0

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(expected_js, encoding="utf-8")
    _print_summary(payload)
    print(f"Architecture map synced: {target_path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

