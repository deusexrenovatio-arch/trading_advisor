from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=str(cwd), check=True)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    hook_dir = repo_root / ".githooks"
    pre_push = hook_dir / "pre-push"

    if not (repo_root / ".git").exists():
        print("error: .git directory not found; run inside repository root")
        return 1
    if not pre_push.exists():
        print("error: missing hook file .githooks/pre-push")
        return 1

    try:
        _run(["git", "config", "core.hooksPath", ".githooks"], cwd=repo_root)
    except subprocess.CalledProcessError as exc:
        print(f"error: failed to set core.hooksPath (.githooks): {exc}")
        return 1

    if os.name != "nt":
        current = pre_push.stat().st_mode
        pre_push.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print("git hooks installed: core.hooksPath=.githooks")
    print("pre-push gate enabled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
