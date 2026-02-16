from __future__ import annotations

import argparse
import itertools
import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import intraday_minute_sweep as base
import moex_carry.pipeline as pipeline_mod
from moex_carry.config import load_settings


def _parse_scenario_specs(value: str) -> list[dict[str, float | int]]:
    specs: list[dict[str, float | int]] = []
    for idx, raw in enumerate(str(value).split(";"), start=1):
        text = raw.strip()
        if not text:
            continue
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 6:
            raise ValueError(
                f"Invalid scenario spec #{idx}: '{text}'. Expected "
                "'lag,wait,stock_tol,future_tol,spread_tol,cutoff'"
            )
        lag_min = int(parts[0])
        wait_min = int(parts[1])
        stock_tol = float(parts[2])
        future_tol = float(parts[3])
        spread_tol = float(parts[4])
        cutoff = int(parts[5])
        specs.append(
            {
                "execution_lag_minutes": lag_min,
                "execution_max_wait_minutes": wait_min,
                "entry_stock_tolerance_pct": stock_tol,
                "entry_future_tolerance_pct": future_tol,
                "entry_spread_tolerance_pct": spread_tol,
                "signal_cutoff_before_day_end_minutes": cutoff,
            }
        )
    if not specs:
        raise ValueError("No valid scenario specs provided")
    return specs


def _build_split_band_fn(
    *,
    stock_tolerance: float,
    future_tolerance: float,
    spread_tolerance: float,
):
    stock_tol = max(float(stock_tolerance), 0.0)
    future_tol = max(float(future_tolerance), 0.0)
    spread_tol = max(float(spread_tolerance), 0.0)

    def _split_band_ok(
        *,
        target_spot: float,
        target_future: float,
        target_spread: float,
        spot_now: float,
        future_now: float,
        spread_now: float,
        tolerance: float,  # kept for signature compatibility
    ) -> bool:
        del tolerance
        if target_spot <= 0 or target_future <= 0:
            return False
        stock_band = target_spot * stock_tol
        future_band = target_future * future_tol
        spread_base = target_spot if target_spot > 0 else max(abs(target_spread), 1.0)
        spread_band = spread_base * spread_tol
        return (
            abs(spot_now - target_spot) <= stock_band
            and abs(future_now - target_future) <= future_band
            and abs(spread_now - target_spread) <= spread_band
        )

    return _split_band_ok


@contextmanager
def _patched_execution_band(
    *,
    stock_tolerance: float,
    future_tolerance: float,
    spread_tolerance: float,
):
    original = pipeline_mod._execution_band_ok
    pipeline_mod._execution_band_ok = _build_split_band_fn(
        stock_tolerance=stock_tolerance,
        future_tolerance=future_tolerance,
        spread_tolerance=spread_tolerance,
    )
    try:
        yield
    finally:
        pipeline_mod._execution_band_ok = original


def _as_float_mean(values: pd.Series) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return None
    return float(clean.mean())


def _build_baseline_row(
    *,
    baseline_scenario_id: str,
    baseline_summary_paths: list[Path],
) -> dict[str, object] | None:
    for path in baseline_summary_paths:
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path)
        except Exception:
            continue
        hit = frame[frame["scenario_id"] == baseline_scenario_id]
        if hit.empty:
            continue
        row = hit.iloc[0].to_dict()
        row["baseline_source"] = str(path).replace("\\", "/")
        return row
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Sweep split stock/future/spread tolerances for intraday minute replay "
            "and compare with baseline scenario."
        )
    )
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--pairs", default=None, help="Comma-separated STOCK:FUTURE list.")
    parser.add_argument("--front-only", action="store_true", help="Select one front future per stock before replay.")
    parser.add_argument("--front-roll-days", type=int, default=7, help="Minimum days-to-expiry for front contract.")
    parser.add_argument("--front-asof-date", default=None, help="As-of date (YYYY-MM-DD) for front selection.")
    parser.add_argument("--front-liquidity-csv", default=None, help="Optional CSV with stock,future and liquidity flag.")
    parser.add_argument("--front-liquidity-column", default="liquidity_pass", help="Liquidity flag column in liquidity CSV.")
    parser.add_argument("--from-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--till-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--lookback-days", type=int, default=140)
    parser.add_argument("--pair-workers", type=int, default=1, help="Parallel workers per scenario over pairs.")
    parser.add_argument("--minute-chunk-days", type=int, default=21, help="Calendar days per chunk for minute fetch.")
    parser.add_argument("--signal-exec-lag-days", type=int, default=0)
    parser.add_argument("--execution-lag-grid", default="30")
    parser.add_argument("--execution-wait-grid", default="360")
    parser.add_argument("--entry-stock-tolerance-grid", default="0.02,0.025,0.03")
    parser.add_argument("--entry-future-tolerance-grid", default="0.008,0.01,0.012,0.015")
    parser.add_argument("--entry-spread-tolerance-grid", default="0.01,0.0125,0.015,0.02")
    parser.add_argument("--cutoff-minutes-grid", default="0")
    parser.add_argument(
        "--preload-cache-mode",
        default="readwrite",
        choices=sorted(base.PRELOAD_CACHE_MODES),
        help="Preload cache mode for pair minute-series preparation.",
    )
    parser.add_argument("--preload-workers", type=int, default=1, help="Parallel workers for cache preload misses.")
    parser.add_argument(
        "--preload-cache-dir",
        default="data/output/intraday_preload_cache",
        help="Directory for preload cache files.",
    )
    parser.add_argument(
        "--scenario-specs",
        default=None,
        help=(
            "Explicit scenario list to avoid grid cross product. "
            "Format: 'lag,wait,stock_tol,future_tol,spread_tol,cutoff;...'"
        ),
    )
    parser.add_argument("--baseline-scenario-id", default="lag30_wait360_tol0.020000_cut0")
    parser.add_argument(
        "--baseline-summary-files",
        default=(
            "data/output/intraday_minute_sweep_lag30_ext_summary.csv,"
            "data/output/intraday_minute_sweep_summary.csv,"
            "data/output/intraday_minute_sweep_lag30_summary.csv"
        ),
    )
    parser.add_argument("--out-pairs-csv", default="data/output/intraday_split_tol_sweep_pairs.csv")
    parser.add_argument("--out-summary-csv", default="data/output/intraday_split_tol_sweep_summary.csv")
    parser.add_argument("--out-summary-json", default="data/output/intraday_split_tol_sweep_summary.json")
    args = parser.parse_args()

    settings_base = load_settings(args.config).model_copy(deep=True)
    settings_base.spread_carry_alpha.price_source = "common_minute_close"
    settings_base.spread_carry_alpha.common_minute_anchor = "last"
    settings_base.spread_carry_alpha.signal_exec_lag_days = max(int(args.signal_exec_lag_days), 0)

    pairs = base._parse_pairs(args.pairs)
    execution_lag_grid = base._parse_int_grid(args.execution_lag_grid)
    execution_wait_grid = base._parse_int_grid(args.execution_wait_grid)
    stock_tol_grid = base._parse_float_grid(args.entry_stock_tolerance_grid)
    future_tol_grid = base._parse_float_grid(args.entry_future_tolerance_grid)
    spread_tol_grid = base._parse_float_grid(args.entry_spread_tolerance_grid)
    cutoff_grid = base._parse_int_grid(args.cutoff_minutes_grid)
    explicit_specs = _parse_scenario_specs(args.scenario_specs) if args.scenario_specs else None

    today = date.today()
    till_date = base._parse_date(args.till_date) if args.till_date else today
    from_date = (
        base._parse_date(args.from_date)
        if args.from_date
        else (till_date - timedelta(days=max(args.lookback_days, 1)))
    )
    if from_date > till_date:
        raise SystemExit("from-date must be <= till-date")
    front_warnings: list[str] = []
    if args.front_only:
        front_asof = base._parse_date(args.front_asof_date) if args.front_asof_date else till_date
        pairs, front_warnings = base.select_front_pairs(
            settings=settings_base,
            pairs=pairs,
            asof_date=front_asof,
            roll_days=args.front_roll_days,
            liquidity_csv=Path(args.front_liquidity_csv) if args.front_liquidity_csv else None,
            liquidity_column=args.front_liquidity_column,
        )
        if not pairs:
            raise SystemExit("No pairs left after front-only filtering")

    baseline_paths = [Path(item.strip()) for item in str(args.baseline_summary_files).split(",") if item.strip()]
    baseline_row = _build_baseline_row(
        baseline_scenario_id=args.baseline_scenario_id,
        baseline_summary_paths=baseline_paths,
    )

    print(
        f"[split-sweep] range={from_date.isoformat()}..{till_date.isoformat()} pairs={len(pairs)} "
        f"lag_days={settings_base.spread_carry_alpha.signal_exec_lag_days}",
        flush=True,
    )
    if args.front_only:
        print(
            f"[split-sweep] front_only enabled roll_days={max(int(args.front_roll_days), 0)} "
            f"asof={(args.front_asof_date or till_date.isoformat())} pairs={len(pairs)}",
            flush=True,
        )
        if front_warnings:
            print(f"[split-sweep] front_only warnings: {front_warnings}", flush=True)
    print(
        f"[split-sweep] preload_cache mode={args.preload_cache_mode} dir={args.preload_cache_dir} "
        f"preload_workers={max(int(args.preload_workers), 1)}",
        flush=True,
    )
    print(
        f"[split-sweep] pair_workers={max(int(args.pair_workers), 1)} "
        f"minute_chunk_days={max(int(args.minute_chunk_days), 1)}",
        flush=True,
    )
    if explicit_specs is None:
        print(
            "[split-sweep] grid: "
            f"lag={execution_lag_grid} wait={execution_wait_grid} "
            f"stock_tol={stock_tol_grid} future_tol={future_tol_grid} spread_tol={spread_tol_grid} "
            f"cutoff={cutoff_grid}",
            flush=True,
        )
    else:
        print(f"[split-sweep] explicit scenarios={len(explicit_specs)}", flush=True)
    if baseline_row is not None:
        print(
            "[split-sweep] baseline="
            f"{args.baseline_scenario_id} from {baseline_row.get('baseline_source')}",
            flush=True,
        )
    else:
        print(f"[split-sweep] baseline {args.baseline_scenario_id} not found in provided files", flush=True)

    cache, preload_errors = base._prepare_pair_cache(
        settings=settings_base,
        pairs=pairs,
        from_date=from_date,
        till_date=till_date,
        preload_cache_dir=Path(args.preload_cache_dir) if args.preload_cache_dir else None,
        preload_cache_mode=args.preload_cache_mode,
        minute_chunk_days=max(int(args.minute_chunk_days), 1),
        preload_workers=max(int(args.preload_workers), 1),
    )
    if not cache:
        raise SystemExit(f"No valid pairs to evaluate. preload_errors={preload_errors}")
    if preload_errors:
        print(f"[split-sweep] preload warnings: {preload_errors}", flush=True)

    if explicit_specs is None:
        combos = list(
            itertools.product(
                execution_lag_grid,
                execution_wait_grid,
                stock_tol_grid,
                future_tol_grid,
                spread_tol_grid,
                cutoff_grid,
            )
        )
    else:
        combos = [
            (
                int(spec["execution_lag_minutes"]),
                int(spec["execution_max_wait_minutes"]),
                float(spec["entry_stock_tolerance_pct"]),
                float(spec["entry_future_tolerance_pct"]),
                float(spec["entry_spread_tolerance_pct"]),
                int(spec["signal_cutoff_before_day_end_minutes"]),
            )
            for spec in explicit_specs
        ]
    print(f"[split-sweep] scenarios={len(combos)}", flush=True)

    pair_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []

    for idx, (lag_min, wait_min, stock_tol, future_tol, spread_tol, cutoff) in enumerate(combos, start=1):
        t0 = time.perf_counter()
        settings = settings_base.model_copy(deep=True)
        alpha = settings.spread_carry_alpha
        alpha.execution_lag_minutes = max(int(lag_min), 0)
        alpha.execution_max_wait_minutes = max(int(wait_min), 1)
        # Keep for observability in replay outputs; actual check is patched below.
        alpha.entry_price_tolerance_pct = max(float(stock_tol), 0.0)
        scenario_id = (
            f"lag{lag_min}_wait{wait_min}_st{stock_tol:.6f}_"
            f"ft{future_tol:.6f}_spt{spread_tol:.6f}_cut{cutoff}"
        )
        print(f"[split-sweep] {idx}/{len(combos)} {scenario_id}", flush=True)

        scenario_pair_rows: list[dict[str, object]] = []
        with _patched_execution_band(
            stock_tolerance=float(stock_tol),
            future_tolerance=float(future_tol),
            spread_tolerance=float(spread_tol),
        ):
            def _eval_item(item: dict[str, object]) -> dict[str, object]:
                pair = item["pair"]
                metrics = base._run_scenario_on_pair(
                    base_series=item["series_base"],
                    cutoff_minutes=int(cutoff),
                    settings=settings,
                    future_spec=item["future_spec"],
                    dividends=item["dividends"],
                    key_rates=item["key_rates"],
                )
                return {
                    "scenario_id": scenario_id,
                    "execution_lag_minutes": int(lag_min),
                    "execution_max_wait_minutes": int(wait_min),
                    "entry_stock_tolerance_pct": float(stock_tol),
                    "entry_future_tolerance_pct": float(future_tol),
                    "entry_spread_tolerance_pct": float(spread_tol),
                    "signal_cutoff_before_day_end_minutes": int(cutoff),
                    "stock": pair.stock,
                    "future": pair.future,
                    **metrics,
                }

            workers = max(int(args.pair_workers), 1)
            if workers <= 1:
                for item in cache:
                    row = _eval_item(item)
                    scenario_pair_rows.append(row)
                    pair_rows.append(row)
            else:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    for row in executor.map(_eval_item, cache):
                        scenario_pair_rows.append(row)
                        pair_rows.append(row)

        frame = pd.DataFrame(scenario_pair_rows)
        valid = frame[frame["error"].isna()]
        unfilled_mean = _as_float_mean(valid["unfilled_entry_rate"]) if not valid.empty else None
        forced_mean = _as_float_mean(valid["forced_exit_rate"]) if not valid.empty else None
        avg_oper_mean = (
            _as_float_mean(valid["avg_trade_return_annual_operational_last5"])
            if not valid.empty
            else None
        )
        closed_total = (
            int(pd.to_numeric(valid["trades_closed"], errors="coerce").fillna(0).sum())
            if not valid.empty
            else 0
        )
        summary_row = {
            "scenario_id": scenario_id,
            "execution_lag_minutes": int(lag_min),
            "execution_max_wait_minutes": int(wait_min),
            "entry_stock_tolerance_pct": float(stock_tol),
            "entry_future_tolerance_pct": float(future_tol),
            "entry_spread_tolerance_pct": float(spread_tol),
            "signal_cutoff_before_day_end_minutes": int(cutoff),
            "pairs_total": int(len(frame)),
            "pairs_ok": int(len(valid)),
            "pairs_failed": int(len(frame) - len(valid)),
            "avg_oper_mean": avg_oper_mean,
            "unfilled_entry_rate_mean": unfilled_mean,
            "forced_exit_rate_mean": forced_mean,
            "trades_closed_total": closed_total,
            "objective_fill_forced_sum": (unfilled_mean if unfilled_mean is not None else 10.0)
            + (forced_mean if forced_mean is not None else 10.0),
            "elapsed_sec": round(time.perf_counter() - t0, 2),
        }
        summary_rows.append(summary_row)
        print(
            f"[split-sweep] {scenario_id} -> unfilled={summary_row['unfilled_entry_rate_mean']} "
            f"forced={summary_row['forced_exit_rate_mean']} avg_oper={summary_row['avg_oper_mean']} "
            f"closed={closed_total}",
            flush=True,
        )

    pair_df = pd.DataFrame(pair_rows)
    summary_df = pd.DataFrame(summary_rows).sort_values(
        ["objective_fill_forced_sum", "unfilled_entry_rate_mean", "forced_exit_rate_mean", "avg_oper_mean"],
        ascending=[True, True, True, False],
    )

    out_pairs = Path(args.out_pairs_csv)
    out_summary = Path(args.out_summary_csv)
    out_json = Path(args.out_summary_json)
    out_pairs.parent.mkdir(parents=True, exist_ok=True)
    pair_df.to_csv(out_pairs, index=False)
    summary_df.to_csv(out_summary, index=False)

    payload: dict[str, object] = {
        "params": {
            "range": {"from": from_date.isoformat(), "till": till_date.isoformat()},
            "pairs": [f"{pair.stock}:{pair.future}" for pair in pairs],
            "signal_exec_lag_days": settings_base.spread_carry_alpha.signal_exec_lag_days,
            "execution_lag_grid": execution_lag_grid,
            "execution_wait_grid": execution_wait_grid,
            "entry_stock_tolerance_grid": stock_tol_grid,
            "entry_future_tolerance_grid": future_tol_grid,
            "entry_spread_tolerance_grid": spread_tol_grid,
            "cutoff_minutes_grid": cutoff_grid,
            "pair_workers": max(int(args.pair_workers), 1),
            "minute_chunk_days": max(int(args.minute_chunk_days), 1),
            "front_only": bool(args.front_only),
            "front_roll_days": max(int(args.front_roll_days), 0),
            "front_asof_date": args.front_asof_date or till_date.isoformat(),
            "front_liquidity_csv": (
                str(args.front_liquidity_csv).replace("\\", "/")
                if args.front_liquidity_csv
                else None
            ),
            "front_liquidity_column": args.front_liquidity_column,
            "preload_cache_mode": args.preload_cache_mode,
            "preload_cache_dir": str(args.preload_cache_dir).replace("\\", "/"),
            "preload_workers": max(int(args.preload_workers), 1),
        },
        "baseline": baseline_row,
        "preload_errors": preload_errors,
        "front_filter_warnings": front_warnings,
        "files": {
            "pairs_csv": str(out_pairs).replace("\\", "/"),
            "summary_csv": str(out_summary).replace("\\", "/"),
        },
        "top10": summary_df.head(10).to_dict(orient="records"),
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[split-sweep] done pairs={out_pairs}", flush=True)
    print(f"[split-sweep] done summary={out_summary}", flush=True)
    print(f"[split-sweep] done top10={out_json}", flush=True)


if __name__ == "__main__":
    main()
