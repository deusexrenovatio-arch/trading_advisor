from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from moex_carry.news.linking_benchmark import evaluate_link_benchmark, load_link_benchmark_cases
from moex_carry.news_live_runtime import NewsIngestConfig


def _write_detail_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "case_id",
        "title",
        "expected_commodities_json",
        "predicted_commodities_json",
        "predicted_scores_json",
        "extra_commodities_json",
        "missing_commodities_json",
        "exact_match",
        "notes",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_report(path: Path, summary: dict[str, object]) -> None:
    lines = [
        "# Multi-Commodity Link Benchmark",
        "",
        f"- Generated at: {datetime.now(timezone.utc).isoformat()}",
        f"- Rows: {summary['rows_total']}",
        f"- False multi-commodity assignment rate: {summary['false_multi_commodity_assignment_rate']:.4f}",
        f"- Assignment precision: {summary['assignment_precision']:.4f}",
        f"- Assignment recall: {summary['assignment_recall']:.4f}",
        f"- Exact match rate: {summary['exact_match_rate']:.4f}",
        f"- Rows with extra links: {summary['rows_with_extra']}",
        f"- Rows with missing links: {summary['rows_with_missing']}",
        f"- Min link score: {summary['min_link_score']}",
        "",
        "Acceptance:",
        "- pass if false multi-commodity assignment rate <= 0.10",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic multi-commodity news linking against a structured benchmark."
    )
    parser.add_argument(
        "--benchmark-csv",
        type=Path,
        default=Path("docs/research/news_multi_commodity_benchmark.csv"),
    )
    parser.add_argument(
        "--news-config",
        type=Path,
        default=Path("configs/news-livecheck-ng.yaml"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--min-link-score",
        type=float,
        default=None,
    )
    args = parser.parse_args()

    if not args.benchmark_csv.exists():
        raise SystemExit(f"Benchmark file not found: {args.benchmark_csv}")
    if not args.news_config.exists():
        raise SystemExit(f"News config not found: {args.news_config}")

    config = NewsIngestConfig.from_yaml(args.news_config)
    allowed_commodities = tuple(profile.ticker for profile in config.commodity_profiles)
    min_link_score = (
        float(args.min_link_score)
        if args.min_link_score is not None
        else float(config.discovery_min_link_score)
    )
    output_dir = args.output_dir or Path("data/output") / (
        "news_multi_commodity_benchmark_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = load_link_benchmark_cases(args.benchmark_csv)
    summary, rows = evaluate_link_benchmark(
        cases=cases,
        allowed_commodities=allowed_commodities,
        min_link_score=min_link_score,
    )
    summary["benchmark_csv"] = str(args.benchmark_csv)
    summary["news_config"] = str(args.news_config)

    (output_dir / "multi_commodity_benchmark_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_detail_csv(output_dir / "multi_commodity_benchmark_details.csv", rows)
    _write_report(output_dir / "multi_commodity_benchmark_report.md", summary)

    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
