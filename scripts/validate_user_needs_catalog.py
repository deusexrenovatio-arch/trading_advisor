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
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _extract_test_cases(doc_path: str) -> set[str]:
    text = Path(doc_path).read_text(encoding="utf-8")
    case_ids: set[str] = set()
    for line in text.splitlines():
        match = TEST_CASE_PATTERN.match(line.strip())
        if match:
            case_ids.add(match.group(1))
    return case_ids


def _required_text(errors: list[str], obj: dict[str, Any], key: str, obj_id: str, obj_kind: str) -> None:
    value = str(obj.get(key, "")).strip()
    if not value:
        errors.append(f"{obj_kind}:{obj_id} missing required field '{key}'")


def _required_list(errors: list[str], obj: dict[str, Any], key: str, obj_id: str, obj_kind: str) -> list[str]:
    raw = obj.get(key)
    if not isinstance(raw, list) or not raw:
        errors.append(f"{obj_kind}:{obj_id} missing non-empty list '{key}'")
        return []
    out: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            out.append(text)
    if not out:
        errors.append(f"{obj_kind}:{obj_id} list '{key}' contains no valid values")
    return out


def run(
    catalog_path: str,
    acceptance_path: str,
    test_cases_path: str,
    *,
    allow_partial_coverage: bool = False,
) -> int:
    catalog = _load_yaml(catalog_path)
    acceptance = _load_yaml(acceptance_path)
    doc_cases = _extract_test_cases(test_cases_path)

    needs = catalog.get("needs") or []
    user_cases = catalog.get("user_cases") or []
    scenarios = acceptance.get("scenarios") or []

    errors: list[str] = []

    if not isinstance(needs, list) or not needs:
        errors.append("catalog must define a non-empty 'needs' list")
        needs = []
    if not isinstance(user_cases, list) or not user_cases:
        errors.append("catalog must define a non-empty 'user_cases' list")
        user_cases = []
    if not isinstance(scenarios, list):
        errors.append("acceptance scenarios file must define 'scenarios' list")
        scenarios = []

    scenario_map: dict[str, set[str]] = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue
        scenario_id = str(scenario.get("id", "")).strip()
        if not scenario_id:
            continue
        tc_values = scenario.get("test_cases") or []
        tc_set = {str(value).strip() for value in tc_values if str(value).strip()}
        scenario_map[scenario_id] = tc_set

    user_case_ids: set[str] = set()
    user_case_ref_count: dict[str, int] = {}
    user_case_scenario_refs: set[str] = set()
    for row in user_cases:
        if not isinstance(row, dict):
            errors.append("user_cases entries must be objects")
            continue
        case_id = str(row.get("id", "")).strip()
        if not case_id:
            errors.append("user_case missing required field 'id'")
            continue
        if case_id in user_case_ids:
            errors.append(f"duplicate user_case id: {case_id}")
            continue
        user_case_ids.add(case_id)
        user_case_ref_count[case_id] = 0

        _required_text(errors, row, "title", case_id, "user_case")
        _required_text(errors, row, "persona", case_id, "user_case")
        _required_text(errors, row, "trigger", case_id, "user_case")
        _required_text(errors, row, "expected_outcome", case_id, "user_case")

        case_scenarios = _required_list(errors, row, "acceptance_scenarios", case_id, "user_case")
        case_tests = _required_list(errors, row, "test_cases", case_id, "user_case")
        user_case_scenario_refs.update(case_scenarios)

        scenario_test_union: set[str] = set()
        for scenario_id in case_scenarios:
            if scenario_id not in scenario_map:
                errors.append(f"user_case:{case_id} references unknown acceptance scenario '{scenario_id}'")
                continue
            scenario_test_union.update(scenario_map[scenario_id])

        for test_case in case_tests:
            if test_case not in doc_cases:
                errors.append(f"user_case:{case_id} references unknown test case '{test_case}'")
            if scenario_test_union and test_case not in scenario_test_union:
                errors.append(
                    f"user_case:{case_id} test case '{test_case}' is not linked from referenced acceptance scenarios"
                )

    need_ids: set[str] = set()
    need_scenario_refs: set[str] = set()
    for row in needs:
        if not isinstance(row, dict):
            errors.append("needs entries must be objects")
            continue
        need_id = str(row.get("id", "")).strip()
        if not need_id:
            errors.append("need missing required field 'id'")
            continue
        if need_id in need_ids:
            errors.append(f"duplicate need id: {need_id}")
            continue
        need_ids.add(need_id)

        _required_text(errors, row, "title", need_id, "need")
        _required_text(errors, row, "problem_statement", need_id, "need")
        _required_text(errors, row, "value_if_solved", need_id, "need")

        need_user_cases = _required_list(errors, row, "user_cases", need_id, "need")
        need_scenarios = _required_list(errors, row, "acceptance_scenarios", need_id, "need")
        need_tests = _required_list(errors, row, "test_cases", need_id, "need")
        need_scenario_refs.update(need_scenarios)

        scenario_test_union: set[str] = set()
        for scenario_id in need_scenarios:
            if scenario_id not in scenario_map:
                errors.append(f"need:{need_id} references unknown acceptance scenario '{scenario_id}'")
                continue
            scenario_test_union.update(scenario_map[scenario_id])

        for case_id in need_user_cases:
            if case_id not in user_case_ids:
                errors.append(f"need:{need_id} references unknown user_case '{case_id}'")
                continue
            user_case_ref_count[case_id] = user_case_ref_count.get(case_id, 0) + 1

        for test_case in need_tests:
            if test_case not in doc_cases:
                errors.append(f"need:{need_id} references unknown test case '{test_case}'")
            if scenario_test_union and test_case not in scenario_test_union:
                errors.append(f"need:{need_id} test case '{test_case}' is not linked from referenced acceptance scenarios")

    for case_id, count in sorted(user_case_ref_count.items()):
        if count == 0:
            errors.append(f"user_case:{case_id} is not referenced by any need")

    covered_scenarios = set(value for value in (need_scenario_refs | user_case_scenario_refs) if value in scenario_map)
    all_scenarios = set(scenario_map)
    uncovered_scenarios = sorted(all_scenarios.difference(covered_scenarios))
    if uncovered_scenarios and not allow_partial_coverage:
        errors.append(
            "catalog does not cover all acceptance scenarios: "
            + ", ".join(uncovered_scenarios)
        )
    coverage_pct = (100.0 * len(covered_scenarios) / len(all_scenarios)) if all_scenarios else 100.0

    if errors:
        print("user-needs catalog validation failed:")
        for item in errors:
            print(f"- {item}")
        return 1

    print("user-needs catalog validation: OK")
    print(
        f"- needs={len(need_ids)} user_cases={len(user_case_ids)} "
        f"scenarios_covered={len(covered_scenarios)}/{len(all_scenarios)} "
        f"coverage_pct={coverage_pct:.2f}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate user-needs catalog mapping to acceptance and test cases")
    parser.add_argument("--catalog", default="configs/user_needs_catalog.yaml")
    parser.add_argument("--acceptance", default="configs/acceptance_scenarios.yaml")
    parser.add_argument("--test-cases", default="docs/test-cases.md")
    parser.add_argument(
        "--allow-partial-coverage",
        action="store_true",
        help="Allow catalog to reference only a subset of acceptance scenarios.",
    )
    args = parser.parse_args()
    sys.exit(
        run(
            args.catalog,
            args.acceptance,
            args.test_cases,
            allow_partial_coverage=bool(args.allow_partial_coverage),
        )
    )


if __name__ == "__main__":
    main()
