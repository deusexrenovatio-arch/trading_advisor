from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("workflow file must be YAML object")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("package.json must be object")
    return payload


def run(workflow_path: Path, package_json_path: Path) -> int:
    errors: list[str] = []

    if not workflow_path.exists():
        errors.append(f"workflow missing: {workflow_path.as_posix()}")
    if not package_json_path.exists():
        errors.append(f"package missing: {package_json_path.as_posix()}")

    if errors:
        print("frontend gate contract failed:")
        for item in errors:
            print(f"- {item}")
        return 1

    workflow = _load_yaml(workflow_path)
    jobs = workflow.get("jobs") or {}
    if not isinstance(jobs, dict) or "frontend" not in jobs:
        errors.append("ci workflow must define jobs.frontend")
    else:
        frontend = jobs.get("frontend") or {}
        if not isinstance(frontend, dict):
            errors.append("jobs.frontend must be an object")
        else:
            steps = frontend.get("steps") or []
            run_commands: list[str] = []
            if isinstance(steps, list):
                for step in steps:
                    if isinstance(step, dict):
                        run_cmd = step.get("run")
                        if isinstance(run_cmd, str):
                            run_commands.append(run_cmd)
            lint_present = any("npm run lint" in cmd for cmd in run_commands)
            build_present = any("npm run build" in cmd for cmd in run_commands)
            if not lint_present:
                errors.append("jobs.frontend must run `npm run lint`")
            if not build_present:
                errors.append("jobs.frontend must run `npm run build`")

    package = _load_json(package_json_path)
    scripts = package.get("scripts") or {}
    if not isinstance(scripts, dict):
        errors.append("ui-web/package.json missing scripts object")
    else:
        if "lint" not in scripts:
            errors.append("ui-web/package.json missing `scripts.lint`")
        if "build" not in scripts:
            errors.append("ui-web/package.json missing `scripts.build`")

    if errors:
        print("frontend gate contract failed:")
        for item in errors:
            print(f"- {item}")
        return 1

    print("frontend gate contract: OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate frontend CI gate contract.")
    parser.add_argument("--workflow", default=".github/workflows/ci.yml")
    parser.add_argument("--package-json", default="ui-web/package.json")
    args = parser.parse_args()
    sys.exit(run(Path(args.workflow), Path(args.package_json)))


if __name__ == "__main__":
    main()
