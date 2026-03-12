from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML object in {path.as_posix()}")
    return payload


def _normalize(path_text: str) -> str:
    cleaned = path_text.replace("\\", "/").strip()
    # Support explicit rename notations from diff tooling (`old -> new`, `old => new`).
    if " -> " in cleaned:
        cleaned = cleaned.split(" -> ", 1)[1].strip()
    elif " => " in cleaned:
        cleaned = cleaned.split(" => ", 1)[1].strip()
    return cleaned.lower()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        marker = _normalize(item)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        out.append(marker)
    return out


def _collect_changed_from_git(git_ref: str) -> list[str]:
    diff_cmd = ["git", "diff", "--name-only", git_ref]
    diff = subprocess.run(diff_cmd, check=False, capture_output=True, text=True)
    if diff.returncode != 0:
        return []
    changed = [line.strip() for line in diff.stdout.splitlines() if line.strip()]
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        check=False,
        capture_output=True,
        text=True,
    )
    if untracked.returncode == 0:
        changed.extend(line.strip() for line in untracked.stdout.splitlines() if line.strip())
    return _dedupe(changed)


def _collect_changed_between_refs(base_ref: str, head_ref: str) -> list[str]:
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}..{head_ref}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0:
        return []
    return _dedupe([line.strip() for line in diff.stdout.splitlines() if line.strip()])


def _collect_changed_from_stdin() -> list[str]:
    return _dedupe([line.strip() for line in sys.stdin.read().splitlines() if line.strip()])


def _match_surface(path_text: str, surface_config: dict[str, Any]) -> bool:
    prefixes = surface_config.get("prefixes") or []
    exclude_prefixes = surface_config.get("exclude_prefixes") or []
    if not isinstance(prefixes, list):
        return False
    if not isinstance(exclude_prefixes, list):
        return False
    normalized = _normalize(path_text)
    for raw_exclude in exclude_prefixes:
        exclude = _normalize(str(raw_exclude))
        if exclude and normalized.startswith(exclude):
            return False
    for raw_prefix in prefixes:
        prefix = _normalize(str(raw_prefix))
        if normalized.startswith(prefix):
            return True
    return False


def _is_docs_only(path_text: str, docs_config: dict[str, Any]) -> bool:
    prefixes = docs_config.get("prefixes") or []
    suffixes = docs_config.get("suffixes") or []
    if not isinstance(prefixes, list) or not isinstance(suffixes, list):
        return False
    normalized = _normalize(path_text)
    return any(normalized.startswith(_normalize(str(prefix))) for prefix in prefixes) and any(
        normalized.endswith(str(suffix).lower()) for suffix in suffixes
    )


def _resolve_command(raw: str) -> str:
    python_exec = sys.executable
    if " " in python_exec:
        python_exec = f"\"{python_exec}\""
    return raw.replace("{python}", python_exec)


def _commands_for_level(
    config: dict[str, Any],
    *,
    level: str,
    surfaces: list[str],
) -> list[str]:
    profiles = config.get("command_profiles") or {}
    level_profile = profiles.get(level) or {}
    if not isinstance(level_profile, dict):
        return []
    candidates: list[str] = []
    for raw in level_profile.get("default") or []:
        candidates.append(_resolve_command(str(raw)))
    for surface in surfaces:
        for raw in level_profile.get(surface) or []:
            candidates.append(_resolve_command(str(raw)))
    return _dedupe(candidates)


def compute_surface(
    changed_files: list[str],
    *,
    mapping_path: Path,
) -> dict[str, Any]:
    changed_files = _dedupe(changed_files)
    config = _load_yaml(mapping_path)
    surfaces_cfg = config.get("surfaces") or {}
    docs_cfg = config.get("docs_only") or {}
    priority = [str(item) for item in config.get("surface_priority") or []]
    surface_matches: dict[str, list[str]] = {}
    matched_markers: set[str] = set()

    for surface_name, surface_config in surfaces_cfg.items():
        if not isinstance(surface_config, dict):
            continue
        matched = [path for path in changed_files if _match_surface(path, surface_config)]
        if matched:
            surface_matches[str(surface_name)] = matched
            matched_markers.update(_normalize(path) for path in matched)

    docs_only = bool(changed_files) and all(_is_docs_only(path, docs_cfg) for path in changed_files)
    unmatched_files = [path for path in changed_files if _normalize(path) not in matched_markers]
    unmatched_non_docs = [path for path in unmatched_files if not _is_docs_only(path, docs_cfg)]
    if unmatched_non_docs and not docs_only:
        governance_files = surface_matches.setdefault("governance", [])
        governance_files.extend(unmatched_non_docs)

    surfaces = sorted(
        surface_matches.keys(),
        key=lambda name: priority.index(name) if name in priority else len(priority),
    )
    non_docs_surfaces = [name for name in surfaces if name != "docs-only"]
    if docs_only and "docs-only" not in surfaces:
        surfaces.append("docs-only")
        surface_matches["docs-only"] = list(changed_files)
    if len([name for name in non_docs_surfaces if name != "governance"]) > 1 and "mixed" not in surfaces:
        surfaces.append("mixed")

    primary_surface = surfaces[0] if surfaces else ("docs-only" if docs_only else "governance")
    if not changed_files:
        primary_surface = "governance"

    return {
        "mapping_path": mapping_path.as_posix(),
        "changed_files": changed_files,
        "surfaces": surfaces or ["governance"],
        "primary_surface": primary_surface,
        "docs_only": docs_only,
        "surface_details": surface_matches,
        "commands": {
            "loop": _commands_for_level(config, level="loop", surfaces=surfaces),
            "pr": _commands_for_level(config, level="pr", surfaces=surfaces),
            "nightly": _commands_for_level(config, level="nightly", surfaces=surfaces),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute canonical change surface classification.")
    parser.add_argument("--mapping", default="configs/change_surface_mapping.yaml")
    parser.add_argument("--from-git", action="store_true")
    parser.add_argument("--git-ref", default="HEAD")
    parser.add_argument("--base-ref", default=None)
    parser.add_argument("--head-ref", default=None)
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--changed-files", nargs="*", default=[])
    parser.add_argument("--output", default=None)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    changed_files: list[str] = list(args.changed_files)
    if args.base_ref and args.head_ref:
        changed_files.extend(_collect_changed_between_refs(args.base_ref, args.head_ref))
    elif args.from_git:
        changed_files.extend(_collect_changed_from_git(args.git_ref))
    if args.stdin:
        changed_files.extend(_collect_changed_from_stdin())
    changed_files = _dedupe(changed_files)

    result = compute_surface(changed_files, mapping_path=Path(args.mapping))
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.format == "text":
        print(f"primary_surface: {result['primary_surface']}")
        print(f"surfaces: {', '.join(result['surfaces'])}")
        print(f"docs_only: {result['docs_only']}")
        for level, commands in result["commands"].items():
            print(f"{level}_commands:")
            for command in commands:
                print(f"- {command}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
