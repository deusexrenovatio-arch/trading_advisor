from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("plans payload must be YAML object")
    return payload


def run(path: Path, stale_days: int | None) -> int:
    if not path.exists():
        print(f"plans file not found: {path.as_posix()}")
        return 1

    payload = _load_yaml(path)
    current_value = str(payload.get("updated_at", "")).strip()
    today = date.today()

    should_update = False
    if not current_value:
        should_update = True
    else:
        current_date = date.fromisoformat(current_value)
        age = (today - current_date).days
        if stale_days is None:
            should_update = True
        else:
            should_update = age > stale_days

    if not should_update:
        print("plans timestamp update: skipped")
        return 0

    payload["updated_at"] = today.isoformat()
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")
    print(f"plans timestamp update: set updated_at={today.isoformat()}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Update plans/PLANS.yaml updated_at timestamp.")
    parser.add_argument("--path", default="plans/PLANS.yaml")
    parser.add_argument("--if-stale-days", type=int, default=None)
    args = parser.parse_args()
    raise SystemExit(run(Path(args.path), args.if_stale_days))


if __name__ == "__main__":
    main()
