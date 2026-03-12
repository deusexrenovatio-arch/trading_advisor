from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("dependency decision policy must be YAML object")
    return payload


def _run_capture(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    return int(completed.returncode), completed.stdout.strip()


def _changed_files(base_sha: str | None, head_sha: str | None) -> list[str]:
    if base_sha and head_sha:
        code, out = _run_capture(["git", "diff", "--name-only", base_sha, head_sha])
        if code == 0:
            changed = {line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()}
            code_untracked, out_untracked = _run_capture(
                ["git", "ls-files", "--others", "--exclude-standard"]
            )
            if code_untracked == 0:
                changed.update(
                    line.strip().replace("\\", "/")
                    for line in out_untracked.splitlines()
                    if line.strip()
                )
            return sorted(changed)

    changed: set[str] = set()
    for command in (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--name-only", "--cached"],
        ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        code, out = _run_capture(command)
        if code != 0:
            continue
        for line in out.splitlines():
            text = line.strip().replace("\\", "/")
            if text:
                changed.add(text)
    return sorted(changed)


def _validate_adr_sections(path: Path, required_sections: list[str]) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    for section in required_sections:
        if section not in text:
            errors.append(f"{path.as_posix()} missing section '{section}'")
    return errors


def run(policy_path: Path, base_sha: str | None, head_sha: str | None) -> int:
    if not policy_path.exists():
        print(f"dependency decision validation failed: missing policy {policy_path.as_posix()}")
        print("remediation: see docs/architecture/adr/README.md")
        return 1

    policy = _load_yaml(policy_path)
    if policy.get("version") != 1:
        print(f"dependency decision validation failed: unsupported version {policy.get('version')!r}")
        print("remediation: see docs/architecture/adr/README.md")
        return 1

    watch_files = policy.get("watch_files") or []
    adr = policy.get("adr") or {}
    if not isinstance(watch_files, list):
        watch_files = []
    if not isinstance(adr, dict):
        adr = {}

    adr_root = Path(str(adr.get("root", "docs/architecture/adr")))
    file_regex = re.compile(str(adr.get("file_regex", r"^docs/architecture/adr/[0-9]{4}-[a-z0-9-]+\.md$")))
    required_sections = adr.get("required_sections") or []
    if not isinstance(required_sections, list):
        required_sections = []

    changed = _changed_files(base_sha, head_sha)
    changed_set = set(changed)
    watched_changed = sorted({item for item in watch_files if str(item).replace("\\", "/") in changed_set})
    adr_changed = sorted([item for item in changed if file_regex.match(item)])

    errors: list[str] = []
    if watched_changed and not adr_changed:
        errors.append(
            "dependency manifests changed without ADR update: "
            + ", ".join(watched_changed)
        )

    if watched_changed:
        for rel in adr_changed:
            adr_path = Path(rel)
            if adr_path.exists():
                errors.extend(_validate_adr_sections(adr_path, [str(x) for x in required_sections]))
        if not adr_root.exists():
            errors.append(f"ADR root missing: {adr_root.as_posix()}")

    if errors:
        print("dependency decision validation failed:")
        for item in errors:
            print(f"- {item}")
        print("remediation: see docs/architecture/adr/README.md")
        return 1

    if watched_changed:
        print(
            "dependency decision validation: OK "
            f"(watched_changed={len(watched_changed)} adr_changed={len(adr_changed)})"
        )
    else:
        print("dependency decision validation: OK (no watched dependency changes)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate ADR updates for dependency/abstraction changes.")
    parser.add_argument("--policy", default="configs/dependency_decision_policy.yaml")
    parser.add_argument("--base-sha", default=None)
    parser.add_argument("--head-sha", default=None)
    args = parser.parse_args()
    sys.exit(run(Path(args.policy), args.base_sha, args.head_sha))


if __name__ == "__main__":
    main()
