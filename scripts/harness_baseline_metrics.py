from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

TEST_CASE_PATTERN = re.compile(r"^###\s+(TC-[A-Z0-9-]+)\b")
SECTION_PATTERN = re.compile(r"^##\s+(.+)$")
FLASK_PARAM_PATTERN = re.compile(r"<(?:[^:>]+:)?([^>]+)>")
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def _load_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML object in {path}")
    return payload


def _extract_doc_cases(doc_path: Path) -> tuple[set[str], set[str]]:
    active_cases: set[str] = set()
    planned_cases: set[str] = set()
    in_planned_section = False
    for line in doc_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        section = SECTION_PATTERN.match(stripped)
        if section:
            section_title = section.group(1).strip().lower()
            in_planned_section = section_title.startswith("planned ")
            continue
        match = TEST_CASE_PATTERN.match(stripped)
        if not match:
            continue
        case_id = match.group(1)
        if in_planned_section:
            planned_cases.add(case_id)
        else:
            active_cases.add(case_id)
    return active_cases, planned_cases


def _count_manual_scenarios(acceptance_path: Path) -> int:
    payload = _load_yaml(acceptance_path)
    scenarios = payload.get("scenarios") or []
    return sum(1 for row in scenarios if isinstance(row, dict) and str(row.get("type", "")).lower() == "manual")


def _count_unlinked_test_cases(acceptance_path: Path, test_cases_path: Path) -> int:
    payload = _load_yaml(acceptance_path)
    scenarios = payload.get("scenarios") or []
    referenced: set[str] = set()
    for row in scenarios:
        if not isinstance(row, dict):
            continue
        for case_id in row.get("test_cases") or []:
            referenced.add(str(case_id))
    active_cases, _planned_cases = _extract_doc_cases(test_cases_path)
    return len(active_cases.difference(referenced))


def _iter_python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _collect_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(str(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(str(node.module))
    return names


def _count_boundary_violations(src_root: Path) -> int:
    ui_root = src_root / "ui"
    allowed = {Path("src/moex_carry/cli.py")}
    count = 0
    for path in _iter_python_files(src_root):
        if _is_under(path, ui_root):
            continue
        if path in allowed:
            continue
        for imported in _collect_imports(path):
            if imported == "moex_carry.ui" or imported.startswith("moex_carry.ui."):
                count += 1
    return count


def _normalize_path(path: str) -> str:
    normalized = FLASK_PARAM_PATTERN.sub(r"{\1}", path.strip())
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if len(normalized) > 1 and normalized.endswith("/"):
        normalized = normalized[:-1]
    return normalized


def _extract_app_ops(app_file: Path, api_prefix: str) -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    tree = ast.parse(app_file.read_text(encoding="utf-8-sig"), filename=str(app_file))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            if not isinstance(dec.func, ast.Attribute) or dec.func.attr != "route":
                continue
            if not dec.args:
                continue
            first = dec.args[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue
            path = _normalize_path(first.value)
            if not path.startswith(api_prefix):
                continue
            methods_kw = next((kw for kw in dec.keywords if kw.arg == "methods"), None)
            methods: set[str] = {"GET"}
            if methods_kw is not None:
                methods = set()
                if isinstance(methods_kw.value, (ast.List, ast.Tuple, ast.Set)):
                    for item in methods_kw.value.elts:
                        if isinstance(item, ast.Constant) and isinstance(item.value, str):
                            methods.add(item.value.upper())
            for method in methods:
                operations.add((method, path))
    return operations


def _normalize_server_prefix(raw: str | None) -> str:
    if not raw:
        return "/api/v2"
    candidate = raw.strip()
    if not candidate:
        return "/api/v2"
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        candidate = parsed.path or ""
    if not candidate:
        return ""
    if not candidate.startswith("/"):
        candidate = f"/{candidate}"
    if len(candidate) > 1 and candidate.endswith("/"):
        candidate = candidate[:-1]
    return candidate


def _join_server_and_path(server_prefix: str, path: str) -> str:
    route = _normalize_path(path)
    if route.startswith("/api/"):
        return route
    if not server_prefix:
        return route
    return _normalize_path(f"{server_prefix}{route}")


def _extract_contract_ops(contract_file: Path) -> set[tuple[str, str]]:
    payload = _load_yaml(contract_file)
    servers = payload.get("servers") or []
    server_url: str | None = None
    if isinstance(servers, list) and servers:
        first = servers[0]
        if isinstance(first, dict):
            raw = first.get("url")
            if isinstance(raw, str):
                server_url = raw
    server_prefix = _normalize_server_prefix(server_url)

    paths = payload.get("paths") or {}
    if not isinstance(paths, dict):
        return set()
    operations: set[tuple[str, str]] = set()
    for path, item in paths.items():
        if not isinstance(path, str) or not isinstance(item, dict):
            continue
        full_path = _join_server_and_path(server_prefix, path)
        for method in item:
            if isinstance(method, str) and method.lower() in HTTP_METHODS:
                operations.add((method.upper(), full_path))
    return operations


def _count_spec_drift(app_files: list[Path], contract_file: Path) -> int:
    app_ops: set[tuple[str, str]] = set()
    for app_file in app_files:
        app_ops.update(_extract_app_ops(app_file, "/api/v2/"))
    contract_ops = _extract_contract_ops(contract_file)
    return len(app_ops.difference(contract_ops)) + len(contract_ops.difference(app_ops))


def _render_summary(metrics: dict[str, int]) -> str:
    lines = [
        "## Harness Baseline Metrics",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    for key in (
        "spec_drift_count",
        "boundary_violations",
        "manual_scenarios_count",
        "unlinked_test_cases_count",
    ):
        lines.append(f"| `{key}` | {metrics[key]} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute Harness baseline metrics.")
    parser.add_argument("--acceptance", default="configs/acceptance_scenarios.yaml")
    parser.add_argument("--test-cases", default="docs/test-cases.md")
    parser.add_argument("--src-root", default="src/moex_carry")
    parser.add_argument("--app-file", action="append", dest="app_files")
    parser.add_argument("--contract-file", default="docs/contracts/api-v2.yaml")
    parser.add_argument("--summary-file", default=None)
    args = parser.parse_args()

    try:
        if args.app_files:
            app_files = [Path(item) for item in args.app_files]
        else:
            ui_root = Path(args.src_root) / "ui"
            app_files = sorted(path for path in ui_root.rglob("*.py") if path.is_file())
        metrics = {
            "spec_drift_count": _count_spec_drift(app_files, Path(args.contract_file)),
            "boundary_violations": _count_boundary_violations(Path(args.src_root)),
            "manual_scenarios_count": _count_manual_scenarios(Path(args.acceptance)),
            "unlinked_test_cases_count": _count_unlinked_test_cases(
                Path(args.acceptance),
                Path(args.test_cases),
            ),
        }
    except Exception as exc:  # pragma: no cover - defensive CI guard
        print(f"ERROR: failed to compute harness baseline metrics: {exc}", file=sys.stderr)
        return 2

    for key, value in metrics.items():
        print(f"{key}={value}")

    if args.summary_file:
        summary_path = Path(args.summary_file)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with summary_path.open("a", encoding="utf-8") as handle:
            handle.write(_render_summary(metrics))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
