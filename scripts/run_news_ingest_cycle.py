from __future__ import annotations

import argparse
import json
from pathlib import Path

from moex_carry.news_live_runtime import NewsIngestConfig, run_news_ingest_cycle


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one commodity-news ingestion cycle.")
    parser.add_argument(
        "--news-config",
        type=str,
        default="configs/news-livecheck-ng.yaml",
        help="Path to news ingestion YAML config",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["live", "backfill"],
        default="live",
        help="Cycle mode",
    )
    args = parser.parse_args()

    config = NewsIngestConfig.from_yaml(Path(args.news_config))
    result = run_news_ingest_cycle(config=config, mode=args.mode)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

