from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
FLASK_PARAM_PATTERN = re.compile(r"<(?:[^:>]+:)?([^>]+)>")


def _normalize_path(path: str) -> str:
    normalized = FLASK_PARAM_PATTERN.sub(r"{\1}", path.strip())
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if len(normalized) > 1 and normalized.endswith("/"):
        normalized = normalized[:-1]
    return normalized


def _extract_route_methods(node: ast.Call) -> set[str]:
    methods_kw = next((kw for kw in node.keywords if kw.arg == "methods"), None)
    if methods_kw is None:
        return {"GET"}
    value = methods_kw.value
    if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return set()
    methods: set[str] = set()
    for item in value.elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            methods.add(item.value.upper())
    return methods


def _extract_app_operations(app_file: Path, api_prefix: str) -> tuple[set[tuple[str, str]], list[str]]:
    source = app_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(app_file))
    operations: set[tuple[str, str]] = set()
    warnings: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not isinstance(func, ast.Attribute) or func.attr != "route":
                continue
            if not decorator.args:
                continue
            first_arg = decorator.args[0]
            if not (isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str)):
                warnings.append(
                    f"{app_file.as_posix()}:{decorator.lineno}: non-literal route path skipped"
                )
                continue
            path = _normalize_path(first_arg.value)
            if not path.startswith(api_prefix):
                continue
            methods = _extract_route_methods(decorator)
            if not methods:
                warnings.append(
                    f"{app_file.as_posix()}:{decorator.lineno}: non-literal methods list skipped"
                )
                continue
            for method in methods:
                operations.add((method, path))
    return operations, warnings


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


def _extract_contract_operations(contract_file: Path) -> tuple[set[tuple[str, str]], str]:
    payload = yaml.safe_load(contract_file.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("OpenAPI payload must be an object")

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
        raise ValueError("'paths' must be an object")

    operations: set[tuple[str, str]] = set()
    for path, spec in paths.items():
        if not isinstance(path, str) or not isinstance(spec, dict):
            continue
        full_path = _join_server_and_path(server_prefix, path)
        for method in spec.keys():
            if not isinstance(method, str):
                continue
            if method.lower() not in HTTP_METHODS:
                continue
            operations.add((method.upper(), full_path))
    return operations, server_prefix or ""


def _print_missing(label: str, items: list[tuple[str, str]]) -> None:
    if not items:
        return
    print(label)
    for method, path in items:
        print(f"- {method} {path}")


def run(*, app_file: Path, contract_file: Path, api_prefix: str) -> int:
    app_operations, warnings = _extract_app_operations(app_file, api_prefix)
    contract_operations, server_prefix = _extract_contract_operations(contract_file)

    only_in_app = sorted(app_operations.difference(contract_operations))
    only_in_contract = sorted(contract_operations.difference(app_operations))

    print(
        "api-v2 parity summary: "
        f"app={len(app_operations)} contract={len(contract_operations)} server_prefix='{server_prefix}'"
    )
    for warning in warnings:
        print(f"warning: {warning}")

    if only_in_app or only_in_contract:
        _print_missing("missing in contract:", only_in_app)
        _print_missing("missing in app:", only_in_contract)
        return 1

    print("api-v2 contract parity: OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate parity between Flask /api/v2 routes and docs/contracts/api-v2.yaml"
    )
    parser.add_argument("--app-file", default="src/moex_carry/ui/app.py")
    parser.add_argument("--contract-file", default="docs/contracts/api-v2.yaml")
    parser.add_argument("--api-prefix", default="/api/v2/")
    args = parser.parse_args()

    app_file = Path(args.app_file)
    contract_file = Path(args.contract_file)
    if not app_file.exists():
        print(f"ERROR: app file not found: {app_file}", file=sys.stderr)
        return 2
    if not contract_file.exists():
        print(f"ERROR: contract file not found: {contract_file}", file=sys.stderr)
        return 2
    return run(app_file=app_file, contract_file=contract_file, api_prefix=str(args.api_prefix))


if __name__ == "__main__":
    raise SystemExit(main())
