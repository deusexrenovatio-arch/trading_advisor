from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

TEST_CASE_PATTERN = re.compile(r"^###\s+(TC-[A-Z0-9-]+)\b")


def _load_yaml(path: str) -> dict[str, Any]:
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}


def _extract_test_cases(doc_path: str) -> set[str]:
    text = Path(doc_path).read_text(encoding="utf-8")
    case_ids: set[str] = set()
    for line in text.splitlines():
        match = TEST_CASE_PATTERN.match(line.strip())
        if match:
            case_ids.add(match.group(1))
    return case_ids


def run(config_path: str, doc_path: str) -> int:
    config = _load_yaml(config_path)
    scenarios = config.get("scenarios") or []
    doc_cases = _extract_test_cases(doc_path)

    referenced: set[str] = set()
    missing_case_links: list[str] = []
    scenarios_missing_links: list[str] = []

    for scenario in scenarios:
        scenario_id = str(scenario.get("id", "scenario"))
        test_cases = scenario.get("test_cases") or []
        if not test_cases:
            scenarios_missing_links.append(scenario_id)
            continue
        for case_id in test_cases:
            case_id = str(case_id)
            referenced.add(case_id)
            if case_id not in doc_cases:
                missing_case_links.append(f"{scenario_id}:{case_id}")

    unlinked_cases = sorted(doc_cases.difference(referenced))

    if scenarios_missing_links:
        print(f"missing test_cases for scenarios: {sorted(scenarios_missing_links)}")
    if missing_case_links:
        print(f"missing test case definitions: {sorted(missing_case_links)}")
    if unlinked_cases:
        print(f"unlinked test cases: {unlinked_cases}")

    if scenarios_missing_links or missing_case_links:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate acceptance test case links")
    parser.add_argument("--config", default="configs/acceptance_scenarios.yaml")
    parser.add_argument("--test-cases", default="docs/test-cases.md")
    args = parser.parse_args()
    sys.exit(run(args.config, args.test_cases))


if __name__ == "__main__":
    main()
