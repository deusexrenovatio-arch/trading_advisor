from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from moex_carry.news_shock_pipeline import (
    LabelPackConfig,
    ShockCurationConfig,
    build_shock_label_pack,
    curate_shock_dataset,
    write_label_pack_jsonl,
)


def _parse_ts(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid timestamp: {value}")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Build high-impact shock label pack for Chat Pro.")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--start-ts", type=str, default=None)
    parser.add_argument("--end-ts", type=str, default=None)
    parser.add_argument("--min-abs-z", type=float, default=2.5)
    parser.add_argument("--max-tasks-total", type=int, default=1200)
    parser.add_argument("--max-tasks-per-day-symbol", type=int, default=20)
    parser.add_argument("--max-delay-min", type=float, default=60.0)
    args = parser.parse_args()

    if not args.input_csv.exists():
        raise SystemExit(f"Input file not found: {args.input_csv}")
    if args.output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output_dir = Path("data/output") / f"shock_label_pack_{stamp}"
    args.output_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.input_csv)
    df["shock_ts_dt"] = pd.to_datetime(df["shock_ts"], utc=True, errors="coerce")
    start = _parse_ts(args.start_ts)
    end = _parse_ts(args.end_ts)
    if start is not None:
        df = df[df["shock_ts_dt"] >= start]
    if end is not None:
        df = df[df["shock_ts_dt"] <= end]
    if df.empty:
        raise SystemExit("No rows after date filtering")
    df = df.drop(columns=["shock_ts_dt"])

    curated, issues, curation_summary = curate_shock_dataset(df, ShockCurationConfig.defaults())
    tasks, pack_summary = build_shock_label_pack(
        curated,
        LabelPackConfig(
            min_abs_z=args.min_abs_z,
            max_tasks_total=args.max_tasks_total,
            max_tasks_per_day_symbol=args.max_tasks_per_day_symbol,
            max_delay_minutes=args.max_delay_min,
        ),
    )
    jsonl_path = args.output_dir / f"shock_label_pack_zge{str(args.min_abs_z).replace('.', 'p')}.jsonl"
    write_label_pack_jsonl(tasks, jsonl_path)
    pack_summary.to_csv(args.output_dir / "shock_label_pack_summary.csv", index=False)
    issues.to_csv(args.output_dir / "shock_label_pack_curation_issues.csv", index=False)
    curation_summary.to_csv(args.output_dir / "shock_label_pack_curation_summary.csv", index=False)

    print("Shock label pack built")
    print(f"rows_input={len(df)} rows_curated={len(curated)} tasks={len(tasks)}")
    print(f"- jsonl: {jsonl_path}")
    print(f"- summary: {args.output_dir / 'shock_label_pack_summary.csv'}")
    print(f"- curation_summary: {args.output_dir / 'shock_label_pack_curation_summary.csv'}")


if __name__ == "__main__":
    main()
