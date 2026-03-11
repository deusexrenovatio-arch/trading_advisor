from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_ROOT_FILES = {
    ".cursorignore",
    ".env.example",
    ".gitignore",
    ".worktree-context.local.json",
    "AGENTS.md",
    "CODEOWNERS",
    "README.md",
    "commitlint.config.cjs",
    "harness-guideline.md",
    "agent-runbook.md",
    "pyproject.toml",
    "docker-compose.yml",
    "docker-compose.observability.yml",
}
ALLOWED_ROOT_DIRS = {
    ".cursor",
    ".git",
    ".githooks",
    ".github",
    ".pytest_cache",
    ".runlogs",
    ".ruff_cache",
    ".tmp",
    ".venv",
    "artifacts",
    "configs",
    "contracts",
    "data",
    "docs",
    "logs",
    "memory",
    "plans",
    "scripts",
    "src",
    "tests",
    "ui-web",
}


def _is_allowed(path: Path) -> bool:
    name = path.name
    if name in ALLOWED_ROOT_DIRS:
        return True
    return name in ALLOWED_ROOT_FILES


def main() -> int:
    parser = argparse.ArgumentParser(description="Nightly root hygiene and drift cleanup for non-product-facing files.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    repo_root = Path.cwd().resolve()
    stale = [
        path for path in repo_root.iterdir() if not _is_allowed(path)
    ]
    if not stale:
        print("nightly root hygiene: OK (no stale root artifacts)")
        return 0

    if not args.apply:
        print("nightly root hygiene: stale root artifacts detected")
        for item in stale:
            print(f"- {item.name}")
        print("run with --apply to archive stale root artifacts")
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    archive_root = repo_root / "docs" / "archive" / "root-hygiene" / stamp
    archive_root.mkdir(parents=True, exist_ok=True)
    for item in stale:
        target = archive_root / item.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(item), str(target))
        print(f"moved: {item.name} -> {target.as_posix()}")

    print(f"nightly root hygiene: archived {len(stale)} artifact(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
