from __future__ import annotations

import argparse
from pathlib import Path

from context_router import route_files


def _collect_significant_python_files(repo_root: Path, src_root: Path) -> list[str]:
    files: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        files.append(path.relative_to(repo_root).as_posix())
    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate that significant moex_carry Python files are mapped to an agent context."
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root path (default: current directory).",
    )
    parser.add_argument(
        "--src-root",
        default="src/moex_carry",
        help="Source root to validate (default: src/moex_carry).",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    src_root = (repo_root / args.src_root).resolve()
    if not src_root.exists():
        print(f"agent context coverage: ERROR (missing source root {src_root})")
        return 2

    significant_files = _collect_significant_python_files(repo_root, src_root)
    result = route_files(significant_files)
    blocking_unmapped = list(result.get("unmapped_files", []))

    if blocking_unmapped:
        print("agent context coverage: FAILED")
        for path in blocking_unmapped:
            print(f"- unmapped significant file: {path}")
        print("remediation: add file coverage to scripts/context_router.py and matching docs/agent-contexts/*.md")
        return 1

    covered_contexts = [
        entry["id"]
        for entry in result.get("contexts", [])
        if isinstance(entry, dict) and entry.get("matched_files_count", 0) > 0
    ]
    print(
        "agent context coverage: OK "
        f"(significant_files={len(significant_files)} contexts={len(covered_contexts)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
