from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import intraday_minute_sweep as base
from moex_carry.config import load_settings


def _parse_pairs_arg(pairs: str | None, pairs_file: str | None) -> list[base.Pair]:
    if pairs:
        return base._parse_pairs(pairs)
    if pairs_file:
        text = Path(pairs_file).read_text(encoding="utf-8").strip()
        return base._parse_pairs(text)
    return base._parse_pairs(None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prewarm intraday preload cache without scenario replay.")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--pairs", default=None, help="Comma-separated STOCK:FUTURE list.")
    parser.add_argument("--pairs-file", default=None, help="Text file with comma-separated STOCK:FUTURE list.")
    parser.add_argument("--front-only", action="store_true")
    parser.add_argument("--front-roll-days", type=int, default=7)
    parser.add_argument("--front-asof-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--front-liquidity-csv", default=None)
    parser.add_argument("--front-liquidity-column", default="liquidity_pass")
    parser.add_argument("--from-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--till-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--lookback-days", type=int, default=400)
    parser.add_argument("--signal-exec-lag-days", type=int, default=0)
    parser.add_argument("--minute-chunk-days", type=int, default=21)
    parser.add_argument(
        "--preload-cache-mode",
        default="readwrite",
        choices=sorted(base.PRELOAD_CACHE_MODES),
    )
    parser.add_argument("--preload-workers", type=int, default=1, help="Parallel workers for cache preload misses.")
    parser.add_argument("--preload-cache-dir", default="data/output/intraday_preload_cache")
    parser.add_argument("--out-summary-csv", default="data/output/front_cache_warmup_summary.csv")
    parser.add_argument("--out-summary-json", default="data/output/front_cache_warmup_summary.json")
    args = parser.parse_args()

    settings = load_settings(args.config).model_copy(deep=True)
    settings.spread_carry_alpha.price_source = "common_minute_close"
    settings.spread_carry_alpha.common_minute_anchor = "last"
    settings.spread_carry_alpha.signal_exec_lag_days = max(int(args.signal_exec_lag_days), 0)

    pairs = _parse_pairs_arg(args.pairs, args.pairs_file)
    today = date.today()
    till_date = base._parse_date(args.till_date) if args.till_date else today
    from_date = (
        base._parse_date(args.from_date)
        if args.from_date
        else till_date - timedelta(days=max(int(args.lookback_days), 1))
    )
    if from_date > till_date:
        raise SystemExit("from-date must be <= till-date")

    front_warnings: list[str] = []
    if args.front_only:
        front_asof = base._parse_date(args.front_asof_date) if args.front_asof_date else till_date
        pairs, front_warnings = base.select_front_pairs(
            settings=settings,
            pairs=pairs,
            asof_date=front_asof,
            roll_days=args.front_roll_days,
            liquidity_csv=Path(args.front_liquidity_csv) if args.front_liquidity_csv else None,
            liquidity_column=args.front_liquidity_column,
        )
        if not pairs:
            raise SystemExit("No pairs left after front-only filtering")

    print(
        f"[cache-warmup] range={from_date.isoformat()}..{till_date.isoformat()} "
        f"pairs={len(pairs)} mode={args.preload_cache_mode} "
        f"chunk_days={max(int(args.minute_chunk_days), 1)} preload_workers={max(int(args.preload_workers), 1)}",
        flush=True,
    )
    if args.front_only:
        print(
            f"[cache-warmup] front_only roll_days={max(int(args.front_roll_days), 0)} "
            f"asof={(args.front_asof_date or till_date.isoformat())}",
            flush=True,
        )
        if front_warnings:
            print(f"[cache-warmup] front warnings: {front_warnings}", flush=True)

    cache, preload_errors = base._prepare_pair_cache(
        settings=settings,
        pairs=pairs,
        from_date=from_date,
        till_date=till_date,
        preload_cache_dir=Path(args.preload_cache_dir) if args.preload_cache_dir else None,
        preload_cache_mode=args.preload_cache_mode,
        minute_chunk_days=max(int(args.minute_chunk_days), 1),
        preload_workers=max(int(args.preload_workers), 1),
    )
    if not cache:
        raise SystemExit(f"Warmup failed: no pairs prepared. preload_errors={preload_errors}")

    rows = []
    for item in cache:
        pair = item["pair"]
        series = item["series_base"]
        rows.append(
            {
                "stock": pair.stock,
                "future": pair.future,
                "rows": int(len(series)),
                "days": int(series["date"].nunique()) if "date" in series.columns else 0,
                "from_date": from_date.isoformat(),
                "till_date": till_date.isoformat(),
            }
        )
    summary_df = pd.DataFrame(rows).sort_values(["stock", "future"])
    out_csv = Path(args.out_summary_csv)
    out_json = Path(args.out_summary_json)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(out_csv, index=False)

    payload = {
        "params": {
            "range": {"from": from_date.isoformat(), "till": till_date.isoformat()},
            "pairs": [f"{p.stock}:{p.future}" for p in pairs],
            "preload_cache_mode": args.preload_cache_mode,
            "preload_cache_dir": str(args.preload_cache_dir).replace("\\", "/"),
            "preload_workers": max(int(args.preload_workers), 1),
            "minute_chunk_days": max(int(args.minute_chunk_days), 1),
            "front_only": bool(args.front_only),
            "front_roll_days": max(int(args.front_roll_days), 0),
            "front_asof_date": args.front_asof_date or till_date.isoformat(),
        },
        "front_filter_warnings": front_warnings,
        "preload_errors": preload_errors,
        "prepared_pairs": int(len(cache)),
        "out_summary_csv": str(out_csv).replace("\\", "/"),
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[cache-warmup] done summary={out_csv}", flush=True)
    print(f"[cache-warmup] done meta={out_json}", flush=True)


if __name__ == "__main__":
    main()
