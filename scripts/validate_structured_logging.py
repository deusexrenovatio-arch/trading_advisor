from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

import yaml


REMEDIATION_DOC = "docs/runbooks/governance-remediation.md"


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("structured logging policy must be a YAML object")
    return payload


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to import module from {path.as_posix()}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(policy_path: Path) -> int:
    if not policy_path.exists():
        print(f"structured logging validation failed: missing policy {policy_path.as_posix()}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    policy = _load_yaml(policy_path)
    if policy.get("version") != 1:
        print(f"structured logging validation failed: unsupported version {policy.get('version')!r}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    schema = policy.get("schema") or {}
    guard = policy.get("guard") or {}
    if not isinstance(schema, dict):
        schema = {}
    if not isinstance(guard, dict):
        guard = {}

    required_fields = schema.get("required_fields") or []
    if not isinstance(required_fields, list):
        required_fields = []
    required = [str(item).strip() for item in required_fields if str(item).strip()]
    event_name = str(schema.get("event") or "api_request_completed").strip()

    api_prefix = str(guard.get("api_prefix") or "/api/v2/").strip()
    app_file = Path(str(guard.get("app_file") or "src/moex_carry/ui/app.py"))
    logging_module_file = Path(str(guard.get("logging_module") or "src/moex_carry/logging.py"))

    errors: list[str] = []
    if not app_file.exists():
        errors.append(f"app file not found: {app_file.as_posix()}")
    if not logging_module_file.exists():
        errors.append(f"logging module not found: {logging_module_file.as_posix()}")

    module = None
    if not errors:
        try:
            module = _load_module(logging_module_file, "_moex_carry_logging_contract")
        except Exception as exc:
            errors.append(f"failed to import logging module: {exc}")

    if module is not None:
        declared_fields = getattr(module, "STRUCTURED_API_LOG_REQUIRED_FIELDS", ())
        if not isinstance(declared_fields, (list, tuple)):
            errors.append("STRUCTURED_API_LOG_REQUIRED_FIELDS must be a list/tuple")
            declared_fields = ()
        declared = [str(item).strip() for item in declared_fields if str(item).strip()]
        missing_declared = [item for item in required if item not in declared]
        if missing_declared:
            errors.append(
                "logging module missing declared structured fields: "
                + ", ".join(missing_declared)
            )

        builder = getattr(module, "build_api_log_event", None)
        if not callable(builder):
            errors.append("build_api_log_event function is missing in logging module")
        else:
            payload = builder(
                component="api-v2",
                path=f"{api_prefix}ops/health",
                method="get",
                status_code=200,
                request_id="req-1",
                duration_ms=12.34,
                event=event_name,
            )
            if not isinstance(payload, dict):
                errors.append("build_api_log_event must return dict")
            else:
                for field in required:
                    if field not in payload:
                        errors.append(f"sample structured payload missing field '{field}'")
                if str(payload.get("event")) != event_name:
                    errors.append(
                        f"sample payload event mismatch: got={payload.get('event')!r} expected={event_name!r}"
                    )
                if str(payload.get("method", "")).upper() != str(payload.get("method", "")):
                    errors.append("sample payload method must be uppercase")

    if app_file.exists():
        app_text = app_file.read_text(encoding="utf-8", errors="ignore")
        guard_a = f'request.path.startswith("{api_prefix}")'
        guard_b = f"request.path.startswith('{api_prefix}')"
        if "emit_api_log(" not in app_text:
            errors.append("app file missing emit_api_log call for API requests")
        if guard_a not in app_text and guard_b not in app_text:
            errors.append(f"app file missing API guard with prefix {api_prefix!r}")

    if errors:
        print("structured logging validation failed:")
        for item in errors:
            print(f"- {item}")
        print(f"remediation: see {REMEDIATION_DOC}")
        return 1

    print(
        "structured logging validation: OK "
        f"(api_prefix={api_prefix} fields={len(required)})"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate structured API logging contract.")
    parser.add_argument("--policy", default="configs/structured_logging_policy.yaml")
    args = parser.parse_args()
    sys.exit(run(Path(args.policy)))


if __name__ == "__main__":
    main()
