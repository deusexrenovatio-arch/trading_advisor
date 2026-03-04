from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from moex_carry.config import load_settings
from moex_carry.news_shock_automation import ShockLabelCycleConfig, run_shock_label_cycle
from moex_carry.news_shock_backfill import ShockRowsBackfillConfig, run_shock_rows_backfill
from moex_carry.news_live_runtime import NewsIngestConfig
from moex_carry.news_shock_readiness import ReadinessConfig


def _parse_sources(raw: str) -> tuple[str, ...] | None:
    text = (raw or "").strip().lower()
    if not text or text == "any":
        return None
    values = tuple(part.strip() for part in text.split(",") if part.strip())
    return values or None


def _parse_utc(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run automated shock labeling cycle.")
    parser.add_argument("--config", type=str, default=None, help="Path to main YAML config.")
    parser.add_argument("--news-config", type=Path, default=Path("configs/news-livecheck-ng.yaml"))
    parser.add_argument("--input-csv", type=Path, default=None)
    parser.add_argument("--input-database-url", type=str, default="sqlite:///./data/news_livecheck_ng.db")
    parser.add_argument("--input-data-dir", type=str, default="./data")
    parser.add_argument("--input-bar-minutes", type=int, default=5)
    parser.add_argument("--input-max-rows", type=int, default=0)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--start-ts", type=str, default=None)
    parser.add_argument("--end-ts", type=str, default=None)
    parser.add_argument("--min-abs-z", type=float, default=2.5)
    parser.add_argument("--max-delay-min", type=float, default=60.0)
    parser.add_argument("--max-tasks-per-day-symbol", type=int, default=20)
    parser.add_argument("--direction-max-tasks", type=int, default=300)
    parser.add_argument("--causal-max-tasks", type=int, default=900)
    parser.add_argument("--direction-candidate-sources", type=str, default="v2_clean")
    parser.add_argument("--causal-candidate-sources", type=str, default="broad,none")
    parser.add_argument("--direction-labels-jsonl", type=Path, default=None)
    parser.add_argument("--causal-labels-jsonl", type=Path, default=None)
    parser.add_argument("--ingest-min-confidence", type=float, default=0.60)
    parser.add_argument("--silver-database-url", type=str, default="sqlite:///./data/news_livecheck_ng.db")
    parser.add_argument("--silver-data-dir", type=str, default="./data")
    parser.add_argument("--no-persist-silver-db", action="store_true")
    parser.add_argument("--no-auto-derive-silver", action="store_true")
    parser.add_argument("--auto-derive-silver-min-abs-z", type=float, default=2.5)
    parser.add_argument("--auto-derive-silver-max-delay-min", type=float, default=120.0)
    parser.add_argument("--auto-derive-silver-min-samples", type=int, default=2)
    parser.add_argument("--auto-derive-silver-min-confidence", type=float, default=0.60)
    parser.add_argument("--no-telegram-feed", action="store_true")
    parser.add_argument(
        "--telegram-feed-path",
        type=Path,
        default=Path("data/output/shock_alerts/live_shocks.csv"),
    )
    parser.add_argument("--telegram-feed-min-abs-z", type=float, default=2.0)
    parser.add_argument("--telegram-feed-max-rows", type=int, default=5000)
    parser.add_argument("--run-readiness", action="store_true")
    parser.add_argument("--primary-z", type=float, default=2.5)
    parser.add_argument("--aftershock-z", type=float, default=2.0)
    parser.add_argument("--episode-window-min", type=int, default=10080)
    parser.add_argument("--max-gap-min", type=int, default=2880)
    parser.add_argument("--run-shock-backfill", action="store_true")
    parser.add_argument("--shock-backfill-cursor-key", type=str, default="shock_rows_backfill_cursor_utc")
    parser.add_argument("--shock-backfill-start-ts", type=str, default="2025-01-01T00:00:00Z")
    parser.add_argument("--shock-backfill-end-ts", type=str, default="")
    parser.add_argument("--shock-backfill-window-hours", type=int, default=24)
    parser.add_argument("--shock-backfill-windows-per-run", type=int, default=5)
    parser.add_argument("--shock-backfill-write-snapshot-csv", action="store_true")
    parser.add_argument(
        "--shock-backfill-snapshot-dir",
        type=str,
        default="data/output/shock_backfill_snapshots",
    )
    args = parser.parse_args()
    if args.input_csv is None and not str(args.input_database_url or "").strip():
        raise SystemExit("Provide --input-csv or --input-database-url.")

    if args.output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output_dir = Path("data/output") / f"shock_label_cycle_{stamp}"

    backfill_payload: dict[str, object] | None = None
    if bool(args.run_shock_backfill):
        if not args.news_config.exists():
            raise FileNotFoundError(f"News config not found: {args.news_config}")
        start_utc = _parse_utc(args.shock_backfill_start_ts)
        if start_utc is None:
            raise ValueError(f"Invalid --shock-backfill-start-ts: {args.shock_backfill_start_ts}")
        end_utc = _parse_utc(args.shock_backfill_end_ts) if str(args.shock_backfill_end_ts).strip() else None
        settings = load_settings(args.config)
        news_cfg = NewsIngestConfig.from_yaml(args.news_config)
        backfill_payload = run_shock_rows_backfill(
            settings=settings,
            news_config=news_cfg,
            cfg=ShockRowsBackfillConfig(
                cursor_key=str(args.shock_backfill_cursor_key),
                start_utc=start_utc,
                end_utc=end_utc,
                window_hours=max(int(args.shock_backfill_window_hours), 1),
                windows_per_run=max(int(args.shock_backfill_windows_per_run), 1),
                bar_minutes=max(int(args.input_bar_minutes), 1),
                min_abs_z=float(args.min_abs_z),
                max_delay_minutes=float(args.max_delay_min),
                news_min_confidence=float(args.ingest_min_confidence),
                write_csv_snapshot=bool(args.shock_backfill_write_snapshot_csv),
                snapshot_dir=str(args.shock_backfill_snapshot_dir),
            ),
        )

    outputs = run_shock_label_cycle(
        input_csv=args.input_csv,
        output_dir=args.output_dir,
        config=ShockLabelCycleConfig(
            min_abs_z=args.min_abs_z,
            max_tasks_per_day_symbol=args.max_tasks_per_day_symbol,
            max_delay_minutes=args.max_delay_min,
            direction_max_tasks_total=args.direction_max_tasks,
            causal_max_tasks_total=args.causal_max_tasks,
            direction_candidate_sources=_parse_sources(args.direction_candidate_sources),
            causal_candidate_sources=_parse_sources(args.causal_candidate_sources),
            ingest_min_confidence=args.ingest_min_confidence,
            persist_ingested_silver_to_db=not bool(args.no_persist_silver_db),
            silver_database_url=args.silver_database_url,
            silver_data_dir=args.silver_data_dir,
            auto_derive_silver_from_curated=not bool(args.no_auto_derive_silver),
            auto_derive_silver_min_abs_z=args.auto_derive_silver_min_abs_z,
            auto_derive_silver_max_delay_minutes=args.auto_derive_silver_max_delay_min,
            auto_derive_silver_min_samples_per_event=args.auto_derive_silver_min_samples,
            auto_derive_silver_min_direction_confidence=args.auto_derive_silver_min_confidence,
            input_database_url=args.input_database_url,
            input_data_dir=args.input_data_dir,
            input_bar_minutes=args.input_bar_minutes,
            input_max_rows=args.input_max_rows,
            export_telegram_feed=not bool(args.no_telegram_feed),
            telegram_feed_path=args.telegram_feed_path,
            telegram_feed_min_abs_z=args.telegram_feed_min_abs_z,
            telegram_feed_max_rows=args.telegram_feed_max_rows,
            run_readiness=args.run_readiness,
            readiness_config=ReadinessConfig(
                max_delay_minutes=args.max_delay_min,
                primary_z_threshold=args.primary_z,
                aftershock_z_threshold=args.aftershock_z,
                episode_window_minutes=args.episode_window_min,
                max_gap_minutes=args.max_gap_min,
            ),
        ),
        start_ts=args.start_ts,
        end_ts=args.end_ts,
        direction_labels_jsonl=args.direction_labels_jsonl,
        causal_labels_jsonl=args.causal_labels_jsonl,
    )
    if isinstance(backfill_payload, dict):
        outputs["shock_rows_backfill"] = backfill_payload

    print("Shock label cycle completed")
    print(f"- output_dir: {outputs.get('output_dir')}")
    print(f"- direction_tasks: {outputs.get('direction_pack', {}).get('tasks_count', 0)}")
    print(f"- causal_tasks: {outputs.get('causal_pack', {}).get('tasks_count', 0)}")
    if isinstance(backfill_payload, dict):
        print(f"- shock_backfill_windows: {backfill_payload.get('windows_processed', 0)}")
        print(f"- shock_backfill_rows: {backfill_payload.get('rows_upserted_total', 0)}")
        print(f"- shock_backfill_cursor_after: {backfill_payload.get('cursor_after')}")
    telegram_feed = outputs.get("telegram_feed")
    if isinstance(telegram_feed, dict):
        print(f"- telegram_feed_rows: {telegram_feed.get('rows', 0)}")
        print(f"- telegram_feed_path: {telegram_feed.get('path')}")
    print(f"- manifest: {outputs.get('manifest_path')}")


if __name__ == "__main__":
    main()
