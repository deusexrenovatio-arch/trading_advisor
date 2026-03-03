from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from moex_carry.news_shock_automation import ShockLabelCycleConfig, run_shock_label_cycle
from moex_carry.news_shock_readiness import ReadinessConfig


def _parse_sources(raw: str) -> tuple[str, ...] | None:
    text = (raw or "").strip().lower()
    if not text or text == "any":
        return None
    values = tuple(part.strip() for part in text.split(",") if part.strip())
    return values or None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run automated shock labeling cycle.")
    parser.add_argument("--input-csv", type=Path, required=True)
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
    args = parser.parse_args()

    if args.output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output_dir = Path("data/output") / f"shock_label_cycle_{stamp}"

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

    print("Shock label cycle completed")
    print(f"- output_dir: {outputs.get('output_dir')}")
    print(f"- direction_tasks: {outputs.get('direction_pack', {}).get('tasks_count', 0)}")
    print(f"- causal_tasks: {outputs.get('causal_pack', {}).get('tasks_count', 0)}")
    telegram_feed = outputs.get("telegram_feed")
    if isinstance(telegram_feed, dict):
        print(f"- telegram_feed_rows: {telegram_feed.get('rows', 0)}")
        print(f"- telegram_feed_path: {telegram_feed.get('path')}")
    print(f"- manifest: {outputs.get('manifest_path')}")


if __name__ == "__main__":
    main()
