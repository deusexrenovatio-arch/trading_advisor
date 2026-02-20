from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


PAIR_FILE_RE = re.compile(r"^intraday_minute_series_([A-Z0-9_]+)_([A-Z0-9_]+)\.csv$")


@dataclass(frozen=True)
class PairCoverage:
    stock: str
    future: str
    days: int
    rows: int
    min_day: str | None
    max_day: str | None

    @property
    def pair_key(self) -> str:
        return f"{self.stock}|{self.future}"


def _to_day_summary(frame: pd.DataFrame) -> tuple[int, int, str | None, str | None]:
    if frame.empty:
        return 0, 0, None, None
    if "date" in frame.columns:
        day_series = pd.to_datetime(frame["date"], errors="coerce").dt.date
    elif "exec_ts" in frame.columns:
        day_series = pd.to_datetime(frame["exec_ts"], errors="coerce").dt.date
    else:
        return 0, int(len(frame)), None, None
    day_series = day_series.dropna()
    if day_series.empty:
        return 0, int(len(frame)), None, None
    return (
        int(day_series.nunique()),
        int(len(frame)),
        day_series.min().isoformat(),
        day_series.max().isoformat(),
    )


def _iter_source_files(root: Path) -> Iterable[tuple[str, str, Path]]:
    for path in sorted(root.glob("intraday_minute_series_*.csv")):
        match = PAIR_FILE_RE.match(path.name)
        if not match:
            continue
        stock, future = match.group(1), match.group(2)
        yield stock.upper(), future.upper(), path


def _load_source_coverage(path: Path, *, stock: str, future: str) -> PairCoverage:
    frame = pd.read_csv(path, usecols=["date", "exec_ts"], low_memory=False)
    days, rows, min_day, max_day = _to_day_summary(frame)
    return PairCoverage(stock=stock, future=future, days=days, rows=rows, min_day=min_day, max_day=max_day)


def _load_replay_coverage(path: Path, *, stock: str, future: str) -> PairCoverage:
    frame = pd.read_parquet(path, columns=["date", "exec_ts"])
    days, rows, min_day, max_day = _to_day_summary(frame)
    return PairCoverage(stock=stock, future=future, days=days, rows=rows, min_day=min_day, max_day=max_day)


def _replay_path(replay_root: Path, *, stock: str, future: str) -> Path:
    safe = f"{stock}__{future}"
    return replay_root / f"{safe}.parquet"


def run(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    source_root = data_dir / "output" / "intraday_minute_series"
    replay_root = data_dir / "output" / "incremental_replay"

    if not source_root.exists():
        print(f"[ERROR] Source folder not found: {source_root}")
        return 2

    source_rows: list[PairCoverage] = []
    missing_replay: list[PairCoverage] = []
    stale_replay: list[tuple[PairCoverage, PairCoverage, int]] = []

    for stock, future, source_path in _iter_source_files(source_root):
        source_cov = _load_source_coverage(source_path, stock=stock, future=future)
        source_rows.append(source_cov)
        replay_path = _replay_path(replay_root, stock=stock, future=future)
        if not replay_path.exists():
            missing_replay.append(source_cov)
            continue
        replay_cov = _load_replay_coverage(replay_path, stock=stock, future=future)
        day_gap = int(source_cov.days - replay_cov.days)
        stale_by_gap = day_gap > int(args.max_day_gap)
        stale_by_min = (
            source_cov.min_day is not None
            and replay_cov.min_day is not None
            and replay_cov.min_day > source_cov.min_day
        )
        stale_by_max = (
            source_cov.max_day is not None
            and replay_cov.max_day is not None
            and replay_cov.max_day < source_cov.max_day
        )
        if stale_by_gap or stale_by_min or stale_by_max:
            stale_replay.append((source_cov, replay_cov, day_gap))

    source_count = len(source_rows)
    short_source = [item for item in source_rows if item.days <= int(args.short_history_days)]
    print(f"[INFO] pairs_source={source_count}")
    print(f"[INFO] pairs_short_history(<= {int(args.short_history_days)}d)={len(short_source)}")
    if source_rows:
        source_days = pd.Series([item.days for item in source_rows], dtype="int64")
        print(
            "[INFO] source_days_quantiles="
            f"min={int(source_days.min())} p25={float(source_days.quantile(0.25)):.1f} "
            f"p50={float(source_days.quantile(0.50)):.1f} p75={float(source_days.quantile(0.75)):.1f} "
            f"max={int(source_days.max())}"
        )

    if missing_replay:
        print(f"[WARN] missing_replay={len(missing_replay)}")
        for item in missing_replay[: int(args.max_print_rows)]:
            print(f"  - {item.pair_key}: source_days={item.days} range={item.min_day}..{item.max_day}")

    if stale_replay:
        print(f"[ERROR] stale_replay={len(stale_replay)} (max_day_gap={int(args.max_day_gap)})")
        for source_cov, replay_cov, day_gap in stale_replay[: int(args.max_print_rows)]:
            print(
                "  - "
                f"{source_cov.pair_key}: source_days={source_cov.days} replay_days={replay_cov.days} "
                f"gap={day_gap} source={source_cov.min_day}..{source_cov.max_day} "
                f"replay={replay_cov.min_day}..{replay_cov.max_day}"
            )
    else:
        print("[OK] replay coverage is consistent with source files")

    # Blockers:
    # 1) stale replay means calculations can be wrong.
    # 2) missing replay can be optionally tolerated for bootstrap.
    if stale_replay:
        return 1
    if missing_replay and not bool(args.allow_missing_replay):
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check source minute series vs incremental replay coverage and detect stale replay state."
    )
    parser.add_argument("--data-dir", default="data", help="Data root directory (default: ./data)")
    parser.add_argument(
        "--max-day-gap",
        type=int,
        default=2,
        help="Maximum allowed source_days - replay_days gap per pair before failure (default: 2)",
    )
    parser.add_argument(
        "--short-history-days",
        type=int,
        default=7,
        help="Threshold for short-history warning in source coverage (default: 7)",
    )
    parser.add_argument(
        "--allow-missing-replay",
        action="store_true",
        help="Do not fail when replay parquet file is missing for some pairs.",
    )
    parser.add_argument(
        "--max-print-rows",
        type=int,
        default=20,
        help="Maximum number of pair rows to print for each issue bucket (default: 20).",
    )
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
