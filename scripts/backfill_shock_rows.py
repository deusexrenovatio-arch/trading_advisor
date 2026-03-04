from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from moex_carry.config import load_settings
from moex_carry.news_live_runtime import NewsIngestConfig
from moex_carry.news_shock_backfill import ShockRowsBackfillConfig, run_shock_rows_backfill


def _parse_utc(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill news_shock_rows in SQLite by historical windows.")
    parser.add_argument("--config", type=str, default=None, help="Path to main YAML config.")
    parser.add_argument("--news-config", type=str, default="configs/news-livecheck-ng.yaml")
    parser.add_argument("--cursor-key", type=str, default="shock_rows_backfill_cursor_utc")
    parser.add_argument("--start-ts", type=str, default="2025-01-01T00:00:00Z")
    parser.add_argument("--end-ts", type=str, default="")
    parser.add_argument("--window-hours", type=int, default=24)
    parser.add_argument("--windows-per-run", type=int, default=5)
    parser.add_argument("--bar-minutes", type=int, default=5)
    parser.add_argument("--min-abs-z", type=float, default=2.0)
    parser.add_argument("--rolling-window-bars", type=int, default=96)
    parser.add_argument("--rolling-min-bars", type=int, default=24)
    parser.add_argument("--max-delay-min", type=float, default=60.0)
    parser.add_argument("--strict-pre-shock-min", type=float, default=10.0)
    parser.add_argument("--broad-context-lookback-min", type=float, default=2880.0)
    parser.add_argument("--v2-min-relevance", type=float, default=0.4)
    parser.add_argument("--broad-min-relevance", type=float, default=0.2)
    parser.add_argument("--cross-commodity-min-relevance", type=float, default=0.8)
    parser.add_argument("--news-min-impact-score", type=float, default=0.35)
    parser.add_argument("--news-min-confidence", type=float, default=0.6)
    parser.add_argument("--news-max-items-per-symbol", type=int, default=3000)
    parser.add_argument("--front-contract-candidates", type=int, default=4)
    parser.add_argument("--history-padding-days", type=int, default=10)
    parser.add_argument("--root-reuse-lookback-min", type=float, default=2880.0)
    parser.add_argument("--write-snapshot-csv", action="store_true")
    parser.add_argument("--snapshot-dir", type=str, default="data/output/shock_backfill_snapshots")
    args = parser.parse_args()

    settings = load_settings(args.config)
    news_cfg = NewsIngestConfig.from_yaml(Path(args.news_config))

    start_utc = _parse_utc(args.start_ts)
    if start_utc is None:
        raise SystemExit("Invalid --start-ts")
    end_utc = _parse_utc(args.end_ts) if str(args.end_ts).strip() else None

    payload = run_shock_rows_backfill(
        settings=settings,
        news_config=news_cfg,
        cfg=ShockRowsBackfillConfig(
            cursor_key=str(args.cursor_key),
            start_utc=start_utc,
            end_utc=end_utc,
            window_hours=int(args.window_hours),
            windows_per_run=int(args.windows_per_run),
            bar_minutes=int(args.bar_minutes),
            min_abs_z=float(args.min_abs_z),
            rolling_window_bars=int(args.rolling_window_bars),
            rolling_min_bars=int(args.rolling_min_bars),
            max_delay_minutes=float(args.max_delay_min),
            strict_pre_shock_minutes=float(args.strict_pre_shock_min),
            broad_context_lookback_minutes=float(args.broad_context_lookback_min),
            v2_min_relevance=float(args.v2_min_relevance),
            broad_min_relevance=float(args.broad_min_relevance),
            cross_commodity_min_relevance=float(args.cross_commodity_min_relevance),
            news_min_impact_score=float(args.news_min_impact_score),
            news_min_confidence=float(args.news_min_confidence),
            news_max_items_per_symbol=int(args.news_max_items_per_symbol),
            front_contract_candidates=int(args.front_contract_candidates),
            history_padding_days=int(args.history_padding_days),
            root_reuse_lookback_minutes=float(args.root_reuse_lookback_min),
            write_csv_snapshot=bool(args.write_snapshot_csv),
            snapshot_dir=str(args.snapshot_dir),
        ),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
