from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML object in {path.as_posix()}")
    return payload


def _iter_python_files(src_root: Path) -> list[Path]:
    if not src_root.exists():
        return []
    return sorted(path for path in src_root.rglob("*.py") if path.is_file())


def _run_capture(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    return int(completed.returncode), completed.stdout.strip()


def _collect_changed_paths(base_sha: str | None, head_sha: str | None) -> list[str]:
    changed: set[str] = set()
    command_candidates: list[list[str]] = []
    if base_sha and head_sha:
        command_candidates.append(["git", "diff", "--name-only", f"{base_sha}..{head_sha}"])
    else:
        github_base_ref = os.getenv("GITHUB_BASE_REF", "").strip()
        if github_base_ref:
            command_candidates.append(
                ["git", "diff", "--name-only", f"origin/{github_base_ref}...HEAD"]
            )
        command_candidates.extend(
            [
                ["git", "diff", "--name-only"],
                ["git", "diff", "--name-only", "--cached"],
            ]
        )
    command_candidates.append(["git", "ls-files", "--others", "--exclude-standard"])

    for command in command_candidates:
        code, out = _run_capture(command)
        if code != 0:
            continue
        for line in out.splitlines():
            normalized = line.strip().replace("\\", "/")
            if normalized:
                changed.add(normalized)
    return sorted(changed)


def _resolve_target_files(
    *,
    src_root: Path,
    explicit_files: list[str],
    all_files: bool,
    base_sha: str | None,
    head_sha: str | None,
) -> tuple[list[Path], str]:
    src_root_resolved = src_root.resolve()
    if all_files:
        return _iter_python_files(src_root_resolved), "all"

    candidates: list[str]
    scope = "changed"
    if explicit_files:
        candidates = [str(item).replace("\\", "/").strip() for item in explicit_files if str(item).strip()]
        scope = "explicit"
    else:
        candidates = _collect_changed_paths(base_sha, head_sha)

    files: list[Path] = []
    seen: set[str] = set()
    for raw in candidates:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if not candidate.exists() or not candidate.is_file() or candidate.suffix != ".py":
            continue
        try:
            candidate.relative_to(src_root_resolved)
        except ValueError:
            continue
        marker = candidate.as_posix().lower()
        if marker in seen:
            continue
        seen.add(marker)
        files.append(candidate)
    return sorted(files), scope


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return sum(1 for _ in handle)


def _is_orchestrator(path_text: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path_text, pattern) for pattern in patterns)


def run(
    config_path: Path,
    src_root: Path,
    *,
    files: list[str],
    all_files: bool,
    base_sha: str | None,
    head_sha: str | None,
) -> int:
    if not config_path.exists():
        print(f"file-size policy validation failed: missing config {config_path.as_posix()}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1
    config = _load_yaml(config_path)
    if config.get("version") != 1:
        print(f"file-size policy validation failed: unsupported version {config.get('version')!r}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    py_cfg = config.get("python") or {}
    if not isinstance(py_cfg, dict):
        py_cfg = {}

    leaf_limit = int(py_cfg.get("leaf_max_lines", 400))
    orchestrator_limit = int(py_cfg.get("orchestrator_max_lines", 700))
    orchestrator_patterns = [
        str(item).replace("\\", "/")
        for item in (py_cfg.get("orchestrator_patterns") or [])
        if str(item).strip()
    ]
    allowlist_raw = py_cfg.get("temporary_facade_allowlist") or {}
    if not isinstance(allowlist_raw, dict):
        allowlist_raw = {}
    allowlist = {
        str(path).replace("\\", "/"): value
        for path, value in allowlist_raw.items()
    }

    target_files, scope = _resolve_target_files(
        src_root=src_root,
        explicit_files=files,
        all_files=all_files,
        base_sha=base_sha,
        head_sha=head_sha,
    )
    if not target_files:
        print("file-size policy validation: OK (files=0 scope=changed)")
        return 0

    errors: list[str] = []
    repo_root = Path.cwd().resolve()
    for path in target_files:
        try:
            rel_path = path.resolve().relative_to(repo_root).as_posix()
        except ValueError:
            rel_path = path.as_posix().replace("\\", "/")
        default_limit = orchestrator_limit if _is_orchestrator(rel_path, orchestrator_patterns) else leaf_limit
        limit = default_limit

        allow_entry = allowlist.get(rel_path)
        if allow_entry is not None:
            if not isinstance(allow_entry, dict):
                errors.append(f"{rel_path}: allowlist entry must be object with max_lines and reason")
            else:
                reason = str(allow_entry.get("reason", "")).strip().lower()
                if not reason.startswith("temporary_facade"):
                    errors.append(
                        f"{rel_path}: allowlist reason must start with 'temporary_facade'"
                    )
                try:
                    limit = int(allow_entry.get("max_lines", default_limit))
                except (TypeError, ValueError):
                    errors.append(f"{rel_path}: allowlist max_lines must be integer")
                    limit = default_limit

        line_count = _count_lines(path)
        if line_count > limit:
            errors.append(f"{rel_path}: {line_count} lines exceeds limit {limit}")

    if errors:
        print("file-size policy validation failed:")
        for item in errors:
            print(f"- {item}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    print(
        "file-size policy validation: OK "
        f"(files={len(target_files)} scope={scope} leaf_max={leaf_limit} orchestrator_max={orchestrator_limit})"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate hard file-size policy with temporary facade allowlist.")
    parser.add_argument("--config", default="configs/file_size_policy.yaml")
    parser.add_argument("--src-root", default="src/moex_carry")
    parser.add_argument("--files", nargs="*", default=[])
    parser.add_argument("--all-files", action="store_true")
    parser.add_argument("--base-sha", default=None)
    parser.add_argument("--head-sha", default=None)
    args = parser.parse_args()
    sys.exit(
        run(
            Path(args.config),
            Path(args.src_root),
            files=list(args.files),
            all_files=bool(args.all_files),
            base_sha=args.base_sha,
            head_sha=args.head_sha,
        )
    )


if __name__ == "__main__":
    main()
