from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml


REQUIRED_SERVICES = ("prometheus", "grafana", "jaeger")
REQUIRED_DOCS = (
    "docs/runbooks/local-observability-stack.md",
    "docs/runbooks/ops-slo-alerts.md",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("compose payload must be YAML object")
    return payload


def run(compose_path: Path) -> int:
    errors: list[str] = []
    if not compose_path.exists():
        errors.append(f"missing compose file: {compose_path.as_posix()}")
    else:
        payload = _load_yaml(compose_path)
        services = payload.get("services") or {}
        if not isinstance(services, dict):
            errors.append("compose.services must be an object")
        else:
            for service in REQUIRED_SERVICES:
                if service not in services:
                    errors.append(f"compose service missing: {service}")

    for doc in REQUIRED_DOCS:
        if not Path(doc).exists():
            errors.append(f"required observability doc missing: {doc}")

    if errors:
        print("observability stack validation failed:")
        for item in errors:
            print(f"- {item}")
        print("remediation: see docs/runbooks/local-observability-stack.md")
        return 1

    print(
        "observability stack validation: OK "
        f"(compose={compose_path.as_posix()} services={','.join(REQUIRED_SERVICES)})"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate local observability stack definition.")
    parser.add_argument("--compose", default="docker-compose.observability.yml")
    args = parser.parse_args()
    sys.exit(run(Path(args.compose)))


if __name__ == "__main__":
    main()
