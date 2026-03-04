from __future__ import annotations

import argparse
import json
from pathlib import Path

from moex_carry.news_silver_store import ingest_event_labels_jsonl_to_db


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest Chat Pro event-level labels into SQLite silver label store.",
    )
    parser.add_argument(
        "--labels-jsonl",
        action="append",
        type=Path,
        required=True,
        help="Path to event-level labels JSONL (repeat option for multiple files).",
    )
    parser.add_argument(
        "--tasks-jsonl",
        type=Path,
        default=None,
        help="Optional tasks JSONL with event context (title/timestamp/symbol hints).",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default="sqlite:///./data/news_livecheck_ng.db",
    )
    parser.add_argument("--data-dir", type=str, default="./data")
    parser.add_argument("--source-tag", type=str, default="chatpro_event")
    parser.add_argument("--min-confidence", type=float, default=0.60)
    parser.add_argument("--min-relevance", type=float, default=0.50)
    args = parser.parse_args()

    total_parsed = 0
    total_stored = 0
    total_high_conf = 0
    per_file: list[dict[str, object]] = []
    for path in args.labels_jsonl:
        result = ingest_event_labels_jsonl_to_db(
            labels_jsonl=path,
            tasks_jsonl=args.tasks_jsonl,
            database_url=args.database_url,
            data_dir=args.data_dir,
            source_tag=args.source_tag,
            min_confidence=args.min_confidence,
            min_relevance=args.min_relevance,
        )
        per_file.append(result)
        total_parsed += int(result.get("records_parsed") or 0)
        total_stored += int(result.get("records_stored") or 0)
        total_high_conf += int(result.get("high_conf_causal") or 0)

    payload = {
        "database_url": args.database_url,
        "data_dir": args.data_dir,
        "source_tag": args.source_tag,
        "files": len(args.labels_jsonl),
        "records_parsed_total": total_parsed,
        "records_stored_total": total_stored,
        "high_conf_causal_total": total_high_conf,
        "per_file": per_file,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
