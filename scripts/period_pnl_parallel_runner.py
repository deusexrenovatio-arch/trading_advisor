from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd


def _split_scenarios(text: str) -> list[str]:
    items = [part.strip() for part in str(text).split(";") if part.strip()]
    if not items:
        raise ValueError("No scenario specs provided")
    return items


def _split_pairs(text: str) -> list[str]:
    parts = [item.strip() for item in re.split(r"[\s,]+", str(text).strip()) if item.strip()]
    if not parts:
        raise ValueError("No pairs provided")
    return parts


def _chunks(items: list[str], parts: int) -> list[list[str]]:
    n = len(items)
    k = max(1, min(parts, n))
    size = math.ceil(n / k)
    return [items[i : i + size] for i in range(0, n, size)]


def _summary_sort(frame: pd.DataFrame) -> pd.DataFrame:
    cols = list(frame.columns)
    if "median_excess_annual_vs_target" in cols:
        return frame.sort_values(
            [
                "median_excess_annual_vs_target",
                "median_realized_annualized_return",
                "unfilled_entry_rate_mean",
                "forced_exit_rate_mean",
            ],
            ascending=[False, False, True, True],
        ).reset_index(drop=True)
    return frame


def _recompute_summary(
    pair_df: pd.DataFrame,
    shard_summary_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if pair_df.empty:
        return pd.DataFrame()

    group_cols = [
        "scenario_id",
        "execution_lag_minutes",
        "execution_max_wait_minutes",
        "entry_stock_tolerance_pct",
        "entry_future_tolerance_pct",
        "entry_spread_tolerance_pct",
        "signal_cutoff_before_day_end_minutes",
    ]
    group_cols = [col for col in group_cols if col in pair_df.columns]
    if not group_cols:
        return pd.DataFrame()

    elapsed_sum: dict[str, float] = {}
    elapsed_max: dict[str, float] = {}
    if (
        shard_summary_df is not None
        and not shard_summary_df.empty
        and "scenario_id" in shard_summary_df.columns
        and "elapsed_sec" in shard_summary_df.columns
    ):
        elapsed_frame = shard_summary_df.copy()
        elapsed_frame["elapsed_sec"] = pd.to_numeric(elapsed_frame["elapsed_sec"], errors="coerce")
        elapsed_frame = elapsed_frame.dropna(subset=["scenario_id", "elapsed_sec"])
        if not elapsed_frame.empty:
            elapsed_sum = elapsed_frame.groupby("scenario_id")["elapsed_sec"].sum().to_dict()
            elapsed_max = elapsed_frame.groupby("scenario_id")["elapsed_sec"].max().to_dict()

    rows: list[dict[str, object]] = []
    for _, frame in pair_df.groupby(group_cols, dropna=False, sort=False):
        valid = frame[frame["error"].isna()] if "error" in frame.columns else frame
        realized_ann = pd.to_numeric(valid.get("realized_annualized_return"), errors="coerce").dropna()
        realized_period = pd.to_numeric(valid.get("realized_period_return"), errors="coerce").dropna()
        excess_ann = pd.to_numeric(valid.get("excess_annual_vs_target"), errors="coerce").dropna()
        unfilled = pd.to_numeric(valid.get("unfilled_entry_rate"), errors="coerce").dropna()
        forced = pd.to_numeric(valid.get("forced_exit_rate"), errors="coerce").dropna()
        idle = pd.to_numeric(valid.get("idle_ratio"), errors="coerce").dropna()
        scenario_id = str(frame["scenario_id"].iloc[0]) if "scenario_id" in frame.columns else None

        row: dict[str, object] = {
            "pairs_total": int(len(frame)),
            "pairs_ok": int(len(valid)),
            "pairs_failed": int(len(frame) - len(valid)),
            "median_realized_annualized_return": float(realized_ann.median()) if not realized_ann.empty else None,
            "mean_realized_annualized_return": float(realized_ann.mean()) if not realized_ann.empty else None,
            "median_realized_period_return": float(realized_period.median()) if not realized_period.empty else None,
            "mean_realized_period_return": float(realized_period.mean()) if not realized_period.empty else None,
            "median_excess_annual_vs_target": float(excess_ann.median()) if not excess_ann.empty else None,
            "mean_excess_annual_vs_target": float(excess_ann.mean()) if not excess_ann.empty else None,
            "unfilled_entry_rate_mean": float(unfilled.mean()) if not unfilled.empty else None,
            "forced_exit_rate_mean": float(forced.mean()) if not forced.empty else None,
            "idle_ratio_mean": float(idle.mean()) if not idle.empty else None,
            "trades_closed_total": int(
                pd.to_numeric(valid.get("trades_closed"), errors="coerce").fillna(0).sum()
            )
            if not valid.empty
            else 0,
        }
        for col in group_cols:
            row[col] = frame[col].iloc[0]
        if scenario_id in elapsed_sum:
            row["elapsed_sec"] = float(elapsed_sum[scenario_id])
        if scenario_id in elapsed_max:
            row["elapsed_sec_parallel_max"] = float(elapsed_max[scenario_id])
        rows.append(row)

    return _summary_sort(pd.DataFrame(rows))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run intraday_period_pnl_eval in parallel over scenario or pair shards and merge outputs."
    )
    parser.add_argument("--python-exe", default=sys.executable)
    parser.add_argument("--jobs", type=int, default=4, help="Parallel subprocesses.")
    parser.add_argument(
        "--shard-axis",
        default="auto",
        choices=["auto", "scenario", "pair"],
        help="Shard by scenario list or pair list. 'auto' picks pair when scenarios <= jobs.",
    )
    parser.add_argument("--scenario-specs", default=None)
    parser.add_argument("--scenario-specs-file", default=None)
    parser.add_argument("--pairs", default=None)
    parser.add_argument("--pairs-file", default=None)
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--lookback-days", type=int, default=400)
    parser.add_argument("--signal-exec-lag-days", type=int, default=0)
    parser.add_argument("--minute-chunk-days", type=int, default=21)
    parser.add_argument("--preload-cache-mode", default="readonly")
    parser.add_argument("--preload-cache-dir", default="data/output/intraday_preload_cache")
    parser.add_argument("--preload-workers", type=int, default=4)
    parser.add_argument("--pair-workers", type=int, default=1)
    parser.add_argument("--front-only", action="store_true")
    parser.add_argument("--front-roll-days", type=int, default=7)
    parser.add_argument("--front-asof-date", default=None)
    parser.add_argument("--front-liquidity-csv", default=None)
    parser.add_argument("--front-liquidity-column", default="liquidity_pass")
    parser.add_argument("--from-date", default=None)
    parser.add_argument("--till-date", default=None)
    parser.add_argument("--tmp-dir", default="data/output/period_parallel_tmp")
    parser.add_argument("--out-pairs-csv", default="data/output/period_parallel_pairs.csv")
    parser.add_argument("--out-summary-csv", default="data/output/period_parallel_summary.csv")
    parser.add_argument("--out-summary-json", default="data/output/period_parallel_summary.json")
    args = parser.parse_args()

    specs_text = args.scenario_specs
    if not specs_text and args.scenario_specs_file:
        specs_text = Path(args.scenario_specs_file).read_text(encoding="utf-8").strip()
    if not specs_text:
        raise SystemExit("Provide --scenario-specs or --scenario-specs-file")
    scenarios = _split_scenarios(specs_text)

    pairs_text = args.pairs
    if not pairs_text and args.pairs_file:
        pairs_text = Path(args.pairs_file).read_text(encoding="utf-8").strip()
    if not pairs_text:
        raise SystemExit("Provide --pairs or --pairs-file")
    pair_tokens = _split_pairs(pairs_text)

    jobs = max(int(args.jobs), 1)
    shard_axis = args.shard_axis
    if shard_axis == "auto":
        shard_axis = "pair" if len(scenarios) <= jobs else "scenario"
    if shard_axis == "pair":
        shards = _chunks(pair_tokens, jobs)
        shard_specs_list = [specs_text] * len(shards)
        shard_pairs_list = [",".join(chunk) for chunk in shards]
    else:
        shards = _chunks(scenarios, jobs)
        shard_specs_list = [";".join(chunk) for chunk in shards]
        shard_pairs_list = [",".join(pair_tokens)] * len(shards)

    tmp_dir = Path(args.tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    procs: list[tuple[subprocess.Popen[str], int, Path, Path, Path]] = []
    print(
        f"[period-parallel] shard_axis={shard_axis} jobs={jobs} "
        f"scenarios={len(scenarios)} pairs={len(pair_tokens)} shards={len(shards)}"
    )

    for idx, shard in enumerate(shards, start=1):
        shard_specs = shard_specs_list[idx - 1]
        shard_pairs_text = shard_pairs_list[idx - 1]
        shard_pairs = tmp_dir / f"pairs_{idx}.csv"
        shard_summary = tmp_dir / f"summary_{idx}.csv"
        shard_json = tmp_dir / f"summary_{idx}.json"
        cmd = [
            args.python_exe,
            "scripts/intraday_period_pnl_eval.py",
            "--config",
            args.config,
            "--pairs",
            shard_pairs_text,
            "--lookback-days",
            str(int(args.lookback_days)),
            "--signal-exec-lag-days",
            str(int(args.signal_exec_lag_days)),
            "--minute-chunk-days",
            str(max(int(args.minute_chunk_days), 1)),
            "--pair-workers",
            str(max(int(args.pair_workers), 1)),
            "--preload-workers",
            str(max(int(args.preload_workers), 1)),
            "--preload-cache-mode",
            args.preload_cache_mode,
            "--preload-cache-dir",
            args.preload_cache_dir,
            "--scenario-specs",
            shard_specs,
            "--out-pairs-csv",
            str(shard_pairs),
            "--out-summary-csv",
            str(shard_summary),
            "--out-summary-json",
            str(shard_json),
        ]
        if args.from_date:
            cmd += ["--from-date", args.from_date]
        if args.till_date:
            cmd += ["--till-date", args.till_date]
        if args.front_only:
            cmd += ["--front-only", "--front-roll-days", str(max(int(args.front_roll_days), 0))]
            if args.front_asof_date:
                cmd += ["--front-asof-date", args.front_asof_date]
            if args.front_liquidity_csv:
                cmd += ["--front-liquidity-csv", args.front_liquidity_csv]
            if args.front_liquidity_column:
                cmd += ["--front-liquidity-column", args.front_liquidity_column]

        shard_pairs_count = len(_split_pairs(shard_pairs_text))
        shard_scenarios_count = len(_split_scenarios(shard_specs))
        print(
            f"[period-parallel] start shard={idx}/{len(shards)} axis={shard_axis} "
            f"scenarios={shard_scenarios_count} pairs={shard_pairs_count}"
        )
        print(f"[period-parallel] cmd: {shlex.join(cmd)}")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        procs.append((proc, idx, shard_pairs, shard_summary, shard_json))

    shard_meta: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for proc, idx, pairs_csv, summary_csv, summary_json in procs:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(f"[shard-{idx}] {line}", end="")
        rc = proc.wait()
        if rc != 0:
            failures.append({"shard": idx, "returncode": rc})
            continue
        shard_meta.append(
            {
                "shard": idx,
                "pairs_csv": str(pairs_csv).replace("\\", "/"),
                "summary_csv": str(summary_csv).replace("\\", "/"),
                "summary_json": str(summary_json).replace("\\", "/"),
            }
        )

    if failures:
        raise SystemExit(f"Some shards failed: {failures}")

    pair_frames = [pd.read_csv(item["pairs_csv"]) for item in shard_meta]
    summary_frames = [pd.read_csv(item["summary_csv"]) for item in shard_meta]
    pair_df = pd.concat(pair_frames, ignore_index=True) if pair_frames else pd.DataFrame()
    shard_summary_df = pd.concat(summary_frames, ignore_index=True) if summary_frames else pd.DataFrame()
    summary_df = _recompute_summary(pair_df, shard_summary_df)
    if summary_df.empty:
        summary_df = _summary_sort(shard_summary_df)

    out_pairs = Path(args.out_pairs_csv)
    out_summary = Path(args.out_summary_csv)
    out_json = Path(args.out_summary_json)
    out_pairs.parent.mkdir(parents=True, exist_ok=True)
    pair_df.to_csv(out_pairs, index=False, quoting=csv.QUOTE_MINIMAL)
    summary_df.to_csv(out_summary, index=False, quoting=csv.QUOTE_MINIMAL)

    payload = {
        "params": {
            "jobs": jobs,
            "shard_axis": shard_axis,
            "scenarios_total": len(scenarios),
            "pairs_total": len(pair_tokens),
            "lookback_days": int(args.lookback_days),
            "pair_workers": max(int(args.pair_workers), 1),
            "preload_workers": max(int(args.preload_workers), 1),
            "minute_chunk_days": max(int(args.minute_chunk_days), 1),
            "preload_cache_mode": args.preload_cache_mode,
            "preload_cache_dir": str(args.preload_cache_dir).replace("\\", "/"),
        },
        "shards": shard_meta,
        "files": {
            "pairs_csv": str(out_pairs).replace("\\", "/"),
            "summary_csv": str(out_summary).replace("\\", "/"),
        },
        "elapsed_sec": round(time.perf_counter() - started, 2),
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[period-parallel] done pairs={out_pairs}")
    print(f"[period-parallel] done summary={out_summary}")
    print(f"[period-parallel] done meta={out_json}")


if __name__ == "__main__":
    main()
