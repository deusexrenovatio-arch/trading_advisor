from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import intraday_minute_sweep as base
import moex_carry.pipeline as pipeline_mod
from moex_carry.config import load_settings
from moex_carry.data.cbr_rates import latest_rate


@dataclass(frozen=True)
class Scenario:
    lag: int
    wait: int
    stock_tol: float
    future_tol: float
    spread_tol: float
    cutoff: int

    @property
    def scenario_id(self) -> str:
        return (
            f"lag{self.lag}_wait{self.wait}_st{self.stock_tol:.6f}_"
            f"ft{self.future_tol:.6f}_spt{self.spread_tol:.6f}_cut{self.cutoff}"
        )


def _parse_scenario_specs(value: str) -> list[Scenario]:
    scenarios: list[Scenario] = []
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
        scenarios.append(
            Scenario(
                lag=int(parts[0]),
                wait=int(parts[1]),
                stock_tol=float(parts[2]),
                future_tol=float(parts[3]),
                spread_tol=float(parts[4]),
                cutoff=int(parts[5]),
            )
        )
    if not scenarios:
        raise ValueError("No valid scenario specs provided")
    return scenarios


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
        tolerance: float,
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


def _target_annual_rate(
    *,
    settings,
    key_rates: list[object],
    period_start: date,
    period_end: date,
) -> float:
    alpha = settings.spread_carry_alpha
    if alpha.annual_target_threshold is not None:
        return float(alpha.annual_target_threshold)
    if alpha.r_cb_annual is not None:
        return float(alpha.r_cb_annual)
    days = pd.date_range(period_start, period_end, freq="D")
    rates: list[float] = []
    for ts in days:
        point = latest_rate(key_rates, ts.date())
        if point is not None and point.rate is not None:
            rates.append(float(point.rate))
    if not rates:
        return 0.0
    return float(pd.Series(rates, dtype="float64").mean())


def _safe_annualize(growth_factor: float, period_days: int, year_basis: float) -> float | None:
    if period_days <= 0:
        return None
    if growth_factor <= 0.0:
        return None
    return float(math.pow(growth_factor, year_basis / float(period_days)) - 1.0)


def _period_pnl_metrics(
    *,
    replay: pd.DataFrame,
    settings,
    key_rates: list[object],
) -> dict[str, object]:
    if replay.empty:
        return {"error": "replay_empty"}

    work = replay.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.date
    work = work.dropna(subset=["date"])
    if work.empty:
        return {"error": "replay_dates_empty"}

    period_start = min(work["date"])
    period_end = max(work["date"])
    period_days = max((period_end - period_start).days, 1)
    year_basis = float(pipeline_mod._day_count_basis(settings.spread_carry_alpha.day_count))

    action = (
        work["signal_action"].astype(str).str.lower()
        if "signal_action" in work.columns
        else pd.Series(dtype="string")
    )
    entry_signals = int((action == "enter").sum())
    exit_signals = int((action == "exit").sum())

    exit_mask = (
        work["exit_flag"].fillna(False).astype(bool)
        if "exit_flag" in work.columns
        else pd.Series(False, index=work.index)
    )
    closed = work.loc[exit_mask].copy()

    trade_returns = pd.to_numeric(closed.get("trade_return_pct_net"), errors="coerce").dropna()
    trade_pnls = pd.to_numeric(closed.get("trade_pnl_cash"), errors="coerce").dropna()
    trade_holds = pd.to_numeric(closed.get("trade_hold_days"), errors="coerce").dropna()

    growth_factor = 1.0
    for value in trade_returns.tolist():
        growth_factor *= (1.0 + float(value))
    period_return = float(growth_factor - 1.0)
    annualized_realized = _safe_annualize(growth_factor, period_days, year_basis)

    target_annual = _target_annual_rate(
        settings=settings,
        key_rates=key_rates,
        period_start=period_start,
        period_end=period_end,
    )
    target_growth = math.pow(1.0 + target_annual, float(period_days) / year_basis)
    target_period_return = float(target_growth - 1.0)

    active_days = float(trade_holds.clip(lower=0).sum()) if not trade_holds.empty else 0.0
    active_ratio = float(min(max(active_days / float(period_days), 0.0), 1.0))
    idle_ratio = float(1.0 - active_ratio)

    execution_stats = pipeline_mod._execution_quality_stats(work)
    open_position_end = False
    if "entry_fill_status" in work.columns and "exit_fill_status" in work.columns:
        pending_entry = work["entry_fill_status"].astype(str).str.lower().eq("filled").sum()
        pending_exit = work["exit_fill_status"].astype(str).str.lower().isin({"filled", "forced"}).sum()
        open_position_end = int(pending_entry) > int(pending_exit)

    excess_annual = (
        float(annualized_realized - target_annual) if annualized_realized is not None else None
    )
    annual_target_pass = (
        bool(annualized_realized >= target_annual) if annualized_realized is not None else None
    )
    period_target_pass = bool(period_return >= target_period_return)

    return {
        "error": None,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "period_days": int(period_days),
        "entry_signals": entry_signals,
        "exit_signals": exit_signals,
        "trades_closed": int(len(trade_returns)),
        "realized_pnl_cash_sum": float(trade_pnls.sum()) if not trade_pnls.empty else 0.0,
        "realized_growth_factor": float(growth_factor),
        "realized_period_return": period_return,
        "realized_annualized_return": annualized_realized,
        "target_annual_rate": float(target_annual),
        "target_period_return": target_period_return,
        "excess_annual_vs_target": excess_annual,
        "annual_target_pass": annual_target_pass,
        "period_target_pass": period_target_pass,
        "active_days_sum": active_days,
        "active_ratio": active_ratio,
        "idle_ratio": idle_ratio,
        "share_target_pass_exit_rows": execution_stats.get("share_target_pass"),
        "unfilled_entry_rate": execution_stats.get("unfilled_entry_rate"),
        "forced_exit_rate": execution_stats.get("forced_exit_rate"),
        "open_position_end": open_position_end,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate real period PnL per pair over the full replay period, including idle time, "
            "and compare against annual target."
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
    parser.add_argument("--lookback-days", type=int, default=400)
    parser.add_argument("--pair-workers", type=int, default=1, help="Parallel workers per scenario over pairs.")
    parser.add_argument("--minute-chunk-days", type=int, default=21, help="Calendar days per chunk for minute fetch.")
    parser.add_argument("--signal-exec-lag-days", type=int, default=0)
    parser.add_argument(
        "--scenario-specs",
        required=True,
        help="Scenario list: 'lag,wait,stock_tol,future_tol,spread_tol,cutoff;...'",
    )
    parser.add_argument(
        "--preload-cache-mode",
        default="readonly",
        choices=sorted(base.PRELOAD_CACHE_MODES),
        help="Preload cache mode for pair minute-series preparation.",
    )
    parser.add_argument("--preload-workers", type=int, default=1, help="Parallel workers for cache preload misses.")
    parser.add_argument(
        "--preload-cache-dir",
        default="data/output/intraday_preload_cache",
        help="Directory for preload cache files.",
    )
    parser.add_argument("--out-pairs-csv", default="data/output/intraday_period_pnl_pairs.csv")
    parser.add_argument("--out-summary-csv", default="data/output/intraday_period_pnl_summary.csv")
    parser.add_argument("--out-summary-json", default="data/output/intraday_period_pnl_summary.json")
    args = parser.parse_args()

    settings_base = load_settings(args.config).model_copy(deep=True)
    settings_base.spread_carry_alpha.price_source = "common_minute_close"
    settings_base.spread_carry_alpha.common_minute_anchor = "last"
    settings_base.spread_carry_alpha.signal_exec_lag_days = max(int(args.signal_exec_lag_days), 0)

    pairs = base._parse_pairs(args.pairs)
    scenarios = _parse_scenario_specs(args.scenario_specs)

    today = date.today()
    till_date = base._parse_date(args.till_date) if args.till_date else today
    from_date = (
        base._parse_date(args.from_date)
        if args.from_date
        else (till_date - timedelta(days=max(int(args.lookback_days), 1)))
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

    print(
        f"[period-pnl] range={from_date.isoformat()}..{till_date.isoformat()} pairs={len(pairs)} "
        f"lag_days={settings_base.spread_carry_alpha.signal_exec_lag_days}",
        flush=True,
    )
    if args.front_only:
        print(
            f"[period-pnl] front_only enabled roll_days={max(int(args.front_roll_days), 0)} "
            f"asof={(args.front_asof_date or till_date.isoformat())} pairs={len(pairs)}",
            flush=True,
        )
        if front_warnings:
            print(f"[period-pnl] front_only warnings: {front_warnings}", flush=True)
    print(
        f"[period-pnl] scenarios={len(scenarios)} preload_cache mode={args.preload_cache_mode} "
        f"dir={args.preload_cache_dir} preload_workers={max(int(args.preload_workers), 1)}",
        flush=True,
    )
    print(
        f"[period-pnl] pair_workers={max(int(args.pair_workers), 1)} "
        f"minute_chunk_days={max(int(args.minute_chunk_days), 1)}",
        flush=True,
    )

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
        print(f"[period-pnl] preload warnings: {preload_errors}", flush=True)

    pair_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []

    for idx, scenario in enumerate(scenarios, start=1):
        t0 = time.perf_counter()
        settings = settings_base.model_copy(deep=True)
        alpha = settings.spread_carry_alpha
        alpha.execution_lag_minutes = max(int(scenario.lag), 0)
        alpha.execution_max_wait_minutes = max(int(scenario.wait), 1)
        alpha.entry_price_tolerance_pct = max(float(scenario.stock_tol), 0.0)

        print(f"[period-pnl] {idx}/{len(scenarios)} {scenario.scenario_id}", flush=True)
        scenario_rows: list[dict[str, object]] = []

        with _patched_execution_band(
            stock_tolerance=scenario.stock_tol,
            future_tolerance=scenario.future_tol,
            spread_tolerance=scenario.spread_tol,
        ):
            def _eval_item(item: dict[str, object]) -> dict[str, object]:
                pair = item["pair"]
                series = base._apply_day_cutoff(item["series_base"], scenario.cutoff)
                if series.empty:
                    return {
                        "scenario_id": scenario.scenario_id,
                        "execution_lag_minutes": int(scenario.lag),
                        "execution_max_wait_minutes": int(scenario.wait),
                        "entry_stock_tolerance_pct": float(scenario.stock_tol),
                        "entry_future_tolerance_pct": float(scenario.future_tol),
                        "entry_spread_tolerance_pct": float(scenario.spread_tol),
                        "signal_cutoff_before_day_end_minutes": int(scenario.cutoff),
                        "stock": pair.stock,
                        "future": pair.future,
                        "error": "series_empty_after_cutoff",
                    }

                replay = pipeline_mod._apply_spread_carry_signals(
                    series,
                    merged=None,
                    dividends=item["dividends"],
                    key_rates=item["key_rates"],
                    settings=settings,
                    future_spec=item["future_spec"],
                    alpha_cfg=settings.spread_carry_alpha,
                )
                metrics = _period_pnl_metrics(
                    replay=replay,
                    settings=settings,
                    key_rates=item["key_rates"],
                )
                return {
                    "scenario_id": scenario.scenario_id,
                    "execution_lag_minutes": int(scenario.lag),
                    "execution_max_wait_minutes": int(scenario.wait),
                    "entry_stock_tolerance_pct": float(scenario.stock_tol),
                    "entry_future_tolerance_pct": float(scenario.future_tol),
                    "entry_spread_tolerance_pct": float(scenario.spread_tol),
                    "signal_cutoff_before_day_end_minutes": int(scenario.cutoff),
                    "stock": pair.stock,
                    "future": pair.future,
                    **metrics,
                }

            workers = max(int(args.pair_workers), 1)
            if workers <= 1:
                for item in cache:
                    row = _eval_item(item)
                    scenario_rows.append(row)
                    pair_rows.append(row)
            else:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    for row in executor.map(_eval_item, cache):
                        scenario_rows.append(row)
                        pair_rows.append(row)

        frame = pd.DataFrame(scenario_rows)
        valid = frame[frame["error"].isna()] if "error" in frame.columns else frame.copy()
        realized_ann = pd.to_numeric(valid.get("realized_annualized_return"), errors="coerce").dropna()
        realized_period = pd.to_numeric(valid.get("realized_period_return"), errors="coerce").dropna()
        excess_ann = pd.to_numeric(valid.get("excess_annual_vs_target"), errors="coerce").dropna()
        unfilled = pd.to_numeric(valid.get("unfilled_entry_rate"), errors="coerce").dropna()
        forced = pd.to_numeric(valid.get("forced_exit_rate"), errors="coerce").dropna()
        idle = pd.to_numeric(valid.get("idle_ratio"), errors="coerce").dropna()
        summary_rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "execution_lag_minutes": int(scenario.lag),
                "execution_max_wait_minutes": int(scenario.wait),
                "entry_stock_tolerance_pct": float(scenario.stock_tol),
                "entry_future_tolerance_pct": float(scenario.future_tol),
                "entry_spread_tolerance_pct": float(scenario.spread_tol),
                "signal_cutoff_before_day_end_minutes": int(scenario.cutoff),
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
                "elapsed_sec": round(time.perf_counter() - t0, 2),
            }
        )

    pair_df = pd.DataFrame(pair_rows)
    summary_df = pd.DataFrame(summary_rows).sort_values(
        [
            "median_excess_annual_vs_target",
            "median_realized_annualized_return",
            "unfilled_entry_rate_mean",
            "forced_exit_rate_mean",
        ],
        ascending=[False, False, True, True],
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
            "scenarios": [scenario.scenario_id for scenario in scenarios],
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
        "preload_errors": preload_errors,
        "front_filter_warnings": front_warnings,
        "files": {
            "pairs_csv": str(out_pairs).replace("\\", "/"),
            "summary_csv": str(out_summary).replace("\\", "/"),
        },
        "top10": summary_df.head(10).to_dict(orient="records"),
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[period-pnl] done pairs={out_pairs}", flush=True)
    print(f"[period-pnl] done summary={out_summary}", flush=True)
    print(f"[period-pnl] done top10={out_json}", flush=True)


if __name__ == "__main__":
    main()
