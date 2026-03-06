from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from moex_carry.news.linking import score_commodity_links


@dataclass(frozen=True)
class CommodityLinkBenchmarkCase:
    case_id: str
    title: str
    description: str
    content: str
    expected_commodities: tuple[str, ...]
    seed_commodities: tuple[str, ...]
    allowed_commodities: tuple[str, ...]
    notes: str


def _parse_json_list(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    text = str(raw).strip()
    if not text:
        return ()
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON list, got: {text}")
    values = []
    for item in parsed:
        normalized = str(item or "").strip().upper()
        if normalized:
            values.append(normalized)
    return tuple(dict.fromkeys(values))


def load_link_benchmark_cases(path: Path) -> list[CommodityLinkBenchmarkCase]:
    rows: list[CommodityLinkBenchmarkCase] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=1):
            case_id = str(row.get("case_id") or "").strip() or f"case-{idx:03d}"
            rows.append(
                CommodityLinkBenchmarkCase(
                    case_id=case_id,
                    title=str(row.get("title") or "").strip(),
                    description=str(row.get("description") or "").strip(),
                    content=str(row.get("content") or "").strip(),
                    expected_commodities=_parse_json_list(row.get("expected_commodities_json")),
                    seed_commodities=_parse_json_list(row.get("seed_commodities_json")),
                    allowed_commodities=_parse_json_list(row.get("allowed_commodities_json")),
                    notes=str(row.get("notes") or "").strip(),
                )
            )
    return rows


def evaluate_link_benchmark(
    *,
    cases: list[CommodityLinkBenchmarkCase],
    allowed_commodities: tuple[str, ...],
    min_link_score: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    universe = tuple(
        dict.fromkeys(str(item or "").strip().upper() for item in allowed_commodities if str(item or "").strip())
    )
    detail_rows: list[dict[str, Any]] = []
    predicted_assignments_total = 0
    expected_assignments_total = 0
    extra_assignments_total = 0
    missing_assignments_total = 0
    exact_matches = 0
    rows_with_extra = 0
    rows_with_missing = 0

    for case in cases:
        case_universe = case.allowed_commodities or universe
        predicted_links = [
            item
            for item in score_commodity_links(
                title=case.title,
                description=case.description,
                content=case.content,
                seed_commodities=list(case.seed_commodities),
            )
            if item.commodity_id in case_universe and float(item.score) >= float(min_link_score)
        ]
        predicted = tuple(item.commodity_id for item in predicted_links)
        expected = tuple(case.expected_commodities)
        extra = tuple(item for item in predicted if item not in expected)
        missing = tuple(item for item in expected if item not in predicted)
        exact_match = not extra and not missing
        if exact_match:
            exact_matches += 1
        if extra:
            rows_with_extra += 1
        if missing:
            rows_with_missing += 1

        predicted_assignments_total += len(predicted)
        expected_assignments_total += len(expected)
        extra_assignments_total += len(extra)
        missing_assignments_total += len(missing)

        detail_rows.append(
            {
                "case_id": case.case_id,
                "title": case.title,
                "expected_commodities_json": json.dumps(list(expected), ensure_ascii=False),
                "predicted_commodities_json": json.dumps(list(predicted), ensure_ascii=False),
                "predicted_scores_json": json.dumps(
                    {item.commodity_id: round(float(item.score), 4) for item in predicted_links},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "extra_commodities_json": json.dumps(list(extra), ensure_ascii=False),
                "missing_commodities_json": json.dumps(list(missing), ensure_ascii=False),
                "exact_match": exact_match,
                "notes": case.notes,
            }
        )

    true_positive_assignments = predicted_assignments_total - extra_assignments_total
    assignment_precision = (
        true_positive_assignments / predicted_assignments_total if predicted_assignments_total else 1.0
    )
    assignment_recall = (
        true_positive_assignments / expected_assignments_total if expected_assignments_total else 1.0
    )
    summary = {
        "rows_total": len(cases),
        "rows_with_extra": rows_with_extra,
        "rows_with_missing": rows_with_missing,
        "exact_match_rate": (exact_matches / len(cases)) if cases else 1.0,
        "predicted_assignments_total": predicted_assignments_total,
        "expected_assignments_total": expected_assignments_total,
        "extra_assignments_total": extra_assignments_total,
        "missing_assignments_total": missing_assignments_total,
        "assignment_precision": float(assignment_precision),
        "assignment_recall": float(assignment_recall),
        "false_multi_commodity_assignment_rate": (
            extra_assignments_total / predicted_assignments_total if predicted_assignments_total else 0.0
        ),
        "allowed_commodities": list(universe),
        "min_link_score": float(min_link_score),
    }
    return summary, detail_rows
