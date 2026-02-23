from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("taste invariants config must be YAML object")
    return payload


def _iter_python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return sum(1 for _ in handle)


def _as_posix(path: Path) -> str:
    return path.as_posix().replace("\\", "/")


def run(config_path: Path, src_root: Path, logging_module: Path) -> int:
    if not config_path.exists():
        print(f"taste invariants validation failed: missing config {config_path.as_posix()}")
        print("remediation: see docs/runbooks/governance-remediation.md")
        return 1

    config = _load_yaml(config_path)
    if config.get("version") != 1:
        print(f"taste invariants validation failed: unsupported version {config.get('version')!r}")
        print("remediation: see docs/runbooks/governance-remediation.md")
        return 1

    errors: list[str] = []
    py_cfg = config.get("python") or {}
    logging_cfg = config.get("logging") or {}
    if not isinstance(py_cfg, dict):
        py_cfg = {}
    if not isinstance(logging_cfg, dict):
        logging_cfg = {}

    max_lines_default = int(py_cfg.get("max_lines_default", 800))
    target_lines_default = int(py_cfg.get("target_lines_default", max_lines_default))
    allowed_large_files = py_cfg.get("allowed_large_files") or {}
    if not isinstance(allowed_large_files, dict):
        allowed_large_files = {}
    allowed_map = {str(key).replace("\\", "/"): int(value) for key, value in allowed_large_files.items()}
    target_large_files = py_cfg.get("target_large_files") or {}
    if not isinstance(target_large_files, dict):
        target_large_files = {}
    target_map = {str(key).replace("\\", "/"): int(value) for key, value in target_large_files.items()}
    target_report_limit = int(py_cfg.get("target_report_limit", 20))

    module_name_pattern = str(py_cfg.get("module_name_regex", r"^[a-z0-9_]+\.py$"))
    module_name_regex = re.compile(module_name_pattern)
    forbid_wildcard_imports = bool(py_cfg.get("forbid_wildcard_imports", True))
    target_budget_overruns: list[tuple[str, int, int]] = []

    for path in _iter_python_files(src_root):
        rel = _as_posix(path)
        name = path.name

        if not module_name_regex.match(name):
            errors.append(f"module naming violation: {rel} (name='{name}')")

        max_lines = allowed_map.get(rel, max_lines_default)
        line_count = _count_lines(path)
        if line_count > max_lines:
            errors.append(f"file too large: {rel} ({line_count} lines > {max_lines})")
        target_lines = target_map.get(rel, target_lines_default)
        if line_count > target_lines:
            target_budget_overruns.append((rel, line_count, target_lines))

        if forbid_wildcard_imports:
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
            if re.search(r"^\s*from\s+\S+\s+import\s+\*", text, flags=re.MULTILINE):
                errors.append(f"wildcard import is forbidden: {rel}")

    if not logging_module.exists():
        errors.append(f"logging module missing: {logging_module.as_posix()}")
    else:
        logging_text = logging_module.read_text(encoding="utf-8-sig", errors="ignore")
        required_tokens = logging_cfg.get("default_format_must_include") or []
        if not isinstance(required_tokens, list):
            required_tokens = []
        for token in required_tokens:
            text = str(token)
            if text and text not in logging_text:
                errors.append(f"logging format token missing in {logging_module.as_posix()}: {text}")

    if errors:
        print("taste invariants validation failed:")
        for item in errors:
            print(f"- {item}")
        print("remediation: see docs/runbooks/governance-remediation.md")
        return 1

    if target_budget_overruns:
        target_budget_overruns.sort(key=lambda item: (item[1] - item[2], item[1]), reverse=True)
        print("taste invariants advisory: target line budget exceeded:")
        for rel, line_count, target_lines in target_budget_overruns[:target_report_limit]:
            print(f"- target budget exceeded: {rel} ({line_count} lines > target {target_lines})")
        omitted = len(target_budget_overruns) - min(len(target_budget_overruns), target_report_limit)
        if omitted > 0:
            print(f"- ... and {omitted} additional file(s)")

    print(
        "taste invariants validation: OK "
        f"(files={len(_iter_python_files(src_root))} "
        f"default_max_lines={max_lines_default} "
        f"target_default_lines={target_lines_default} "
        f"target_overruns={len(target_budget_overruns)})"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate enforceable engineering taste invariants.")
    parser.add_argument("--config", default="configs/taste_invariants.yaml")
    parser.add_argument("--src-root", default="src/moex_carry")
    parser.add_argument("--logging-module", default="src/moex_carry/logging.py")
    args = parser.parse_args()
    sys.exit(
        run(
            config_path=Path(args.config),
            src_root=Path(args.src_root),
            logging_module=Path(args.logging_module),
        )
    )


if __name__ == "__main__":
    main()
