from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from moex_carry.news_shock_readiness import ReadinessConfig, run_readiness_assessment


def main() -> None:
    parser = argparse.ArgumentParser(description="Run launch-readiness assessment for shock-news workflow.")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--start-ts", type=str, default=None)
    parser.add_argument("--end-ts", type=str, default=None)
    parser.add_argument("--max-delay-min", type=float, default=60.0)
    parser.add_argument("--primary-z", type=float, default=2.5)
    parser.add_argument("--aftershock-z", type=float, default=2.0)
    parser.add_argument("--episode-window-min", type=int, default=10080)
    parser.add_argument("--max-gap-min", type=int, default=2880)
    args = parser.parse_args()

    if not args.input_csv.exists():
        raise SystemExit(f"Input file not found: {args.input_csv}")
    if args.output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output_dir = Path("data/output") / f"news_shock_readiness_{stamp}"

    outputs = run_readiness_assessment(
        input_csv=args.input_csv,
        output_dir=args.output_dir,
        config=ReadinessConfig(
            max_delay_minutes=args.max_delay_min,
            primary_z_threshold=args.primary_z,
            aftershock_z_threshold=args.aftershock_z,
            episode_window_minutes=args.episode_window_min,
            max_gap_minutes=args.max_gap_min,
        ),
        start_ts=args.start_ts,
        end_ts=args.end_ts,
    )
    print("News shock readiness completed")
    for key, path in outputs.items():
        print(f"- {key}: {path}")


if __name__ == "__main__":
    main()
