from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from moex_carry.news_shock_pipeline import ingest_chat_labels


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Chat Pro labels and build silver dataset.")
    parser.add_argument("--tasks-jsonl", type=Path, required=True)
    parser.add_argument("--labels-jsonl", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--min-confidence", type=float, default=0.60)
    args = parser.parse_args()

    if args.output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output_dir = Path("data/output") / f"shock_silver_ingest_{stamp}"
    args.output_dir.mkdir(parents=True, exist_ok=True)

    merged, summary = ingest_chat_labels(
        tasks_jsonl=args.tasks_jsonl,
        labels_jsonl=args.labels_jsonl,
        min_confidence=args.min_confidence,
    )
    merged_path = args.output_dir / "shock_silver_labels.csv"
    summary_path = args.output_dir / "shock_silver_labels_summary.csv"
    merged.to_csv(merged_path, index=False)
    summary.to_csv(summary_path, index=False)

    high_conf = int((merged.get("is_high_conf", 0) == 1).sum()) if not merged.empty else 0
    print("Shock labels ingested")
    print(f"rows_total={len(merged)} high_conf={high_conf}")
    print(f"- labels: {merged_path}")
    print(f"- summary: {summary_path}")


if __name__ == "__main__":
    main()
