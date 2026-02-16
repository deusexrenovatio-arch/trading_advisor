from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from moex_carry.config import AppSettings, load_settings, resolve_paths
from moex_carry.data import MoexIssClient
from moex_carry.pipeline import (
    _apply_spread_carry_signals,
    _avg_recent_trade_return_annual,
    _avg_recent_trade_return_annual_operational,
    _data_paths,
    _execution_quality_stats,
    _fetch_minute_candles_chunked,
    _future_price_scale,
    _load_dividends,
    _load_key_rates,
    _parse_contract_specs,
    compute_spread_series,
)


@dataclass(frozen=True)
class Pair:
    stock: str
    future: str


DEFAULT_PAIRS = [
    Pair("FLOT", "FLH6"),
    Pair("AFLT", "AFH6"),
    Pair("ALRS", "ALH6"),
    Pair("CHMF", "CHH6"),
    Pair("GMKN", "GKH6"),
    Pair("CBOM", "CMH6"),
]


def _parse_pairs(value: str | None) -> list[Pair]:
    if not value:
        return list(DEFAULT_PAIRS)
    pairs: list[Pair] = []
    for raw in value.split(","):
        text = raw.strip()
        if not text:
            continue
        if ":" not in text:
            raise ValueError(f"Invalid pair format '{text}'. Use STOCK:FUTURE")
        stock, future = text.split(":", 1)
        stock = stock.strip().upper()
        future = future.strip().upper()
        if not stock or not future:
            raise ValueError(f"Invalid pair format '{text}'. Use STOCK:FUTURE")
        pairs.append(Pair(stock, future))
    if not pairs:
        raise ValueError("No pairs provided")
    return pairs


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _build_client(settings: AppSettings) -> MoexIssClient:
    return MoexIssClient(
        settings.moex.base_url,
        settings.moex.request_timeout_sec,
        max_retries=settings.moex.request_max_retries,
        retry_backoff_sec=settings.moex.request_retry_backoff_sec,
        retry_max_backoff_sec=settings.moex.request_retry_max_backoff_sec,
        fallback_ips=settings.moex.fallback_ips,
        force_fallback=settings.moex.force_fallback,
    )


def _load_future_specs(data_dir: Path):
    futures_path = data_dir / "raw" / "futures.csv"
    if not futures_path.exists():
        raise FileNotFoundError(f"Missing futures metadata: {futures_path}")
    futures_df = pd.read_csv(futures_path)
    return {spec.secid: spec for spec in _parse_contract_specs(futures_df)}


def _fetch_common_minute_rows(
    *,
    client: MoexIssClient,
    settings: AppSettings,
    stock: str,
    future: str,
    from_date: date,
    till_date: date,
    future_scale: float,
) -> pd.DataFrame:
    stock_df = _fetch_minute_candles_chunked(
        client,
        engine=settings.moex.engine_shares,
        market=settings.moex.market_shares,
        board=settings.moex.shares_board,
        secid=stock,
        from_date=from_date,
        till_date=till_date,
        price_scale=1.0,
    )
    future_df = _fetch_minute_candles_chunked(
        client,
        engine=settings.moex.engine_futures,
        market=settings.moex.market_futures,
        board=settings.moex.futures_board,
        secid=future,
        from_date=from_date,
        till_date=till_date,
        price_scale=future_scale,
    )
    if stock_df.empty or future_df.empty:
        return pd.DataFrame(columns=["date", "spot", "future", "spot_volume", "future_volume", "exec_ts"])

    joined = stock_df.merge(
        future_df,
        on="ts",
        how="inner",
        suffixes=("_stock", "_future"),
    )
    if joined.empty:
        return pd.DataFrame(columns=["date", "spot", "future", "spot_volume", "future_volume", "exec_ts"])

    joined = joined.sort_values("ts")
    joined["date"] = pd.to_datetime(joined["ts"]).dt.date
    joined = joined.rename(
        columns={
            "price_stock": "spot",
            "price_future": "future",
            "volume_stock": "spot_volume",
            "volume_future": "future_volume",
            "ts": "exec_ts",
        }
    )
    return joined[["date", "spot", "future", "spot_volume", "future_volume", "exec_ts"]].reset_index(drop=True)


def _run_pair(
    *,
    pair: Pair,
    settings: AppSettings,
    client: MoexIssClient,
    from_date: date,
    till_date: date,
    future_specs: dict[str, object],
    dirs: dict[str, Path],
    save_series_dir: Path | None,
) -> dict[str, object]:
    started = time.perf_counter()
    future_spec = future_specs.get(pair.future)
    if future_spec is None:
        elapsed = time.perf_counter() - started
        return {
            "stock": pair.stock,
            "future": pair.future,
            "rows": 0,
            "days": 0,
            "entry_signals": 0,
            "exit_signals": 0,
            "trades_closed": 0,
            "avg_trade_return_annual_fill_to_fill_last5": None,
            "avg_trade_return_annual_operational_last5": None,
            "share_target_pass": None,
            "unfilled_entry_rate": None,
            "unfilled_exit_rate": None,
            "forced_exit_rate": None,
            "avg_entry_wait_min_closed": None,
            "avg_exit_wait_min_closed": None,
            "elapsed_sec": round(elapsed, 2),
            "error": "future_spec_not_found",
        }

    future_scale = _future_price_scale(future_spec)
    merged = _fetch_common_minute_rows(
        client=client,
        settings=settings,
        stock=pair.stock,
        future=pair.future,
        from_date=from_date,
        till_date=till_date,
        future_scale=future_scale,
    )
    if merged.empty:
        elapsed = time.perf_counter() - started
        return {
            "stock": pair.stock,
            "future": pair.future,
            "rows": 0,
            "days": 0,
            "entry_signals": 0,
            "exit_signals": 0,
            "trades_closed": 0,
            "avg_trade_return_annual_fill_to_fill_last5": None,
            "avg_trade_return_annual_operational_last5": None,
            "share_target_pass": None,
            "unfilled_entry_rate": None,
            "unfilled_exit_rate": None,
            "forced_exit_rate": None,
            "avg_entry_wait_min_closed": None,
            "avg_exit_wait_min_closed": None,
            "elapsed_sec": round(elapsed, 2),
            "error": "no_common_minutes",
        }

    dividends = _load_dividends(client, pair.stock, resolve_paths(settings).data_dir)
    key_rates = _load_key_rates(dirs["raw"] / "key_rates.csv")
    alpha_cfg = settings.spread_carry_alpha

    prices = merged[["date", "spot", "future"]].rename(columns={"future": "future_price"})
    series_df = compute_spread_series(
        prices,
        future_spec.expiry,
        dividends,
        key_rates,
        r_disc_annual=alpha_cfg.r_disc_annual,
        day_count=alpha_cfg.day_count,
    )
    if series_df.empty:
        elapsed = time.perf_counter() - started
        return {
            "stock": pair.stock,
            "future": pair.future,
            "rows": 0,
            "days": 0,
            "entry_signals": 0,
            "exit_signals": 0,
            "trades_closed": 0,
            "avg_trade_return_annual_fill_to_fill_last5": None,
            "avg_trade_return_annual_operational_last5": None,
            "share_target_pass": None,
            "unfilled_entry_rate": None,
            "unfilled_exit_rate": None,
            "forced_exit_rate": None,
            "avg_entry_wait_min_closed": None,
            "avg_exit_wait_min_closed": None,
            "elapsed_sec": round(elapsed, 2),
            "error": "empty_spread_series",
        }

    series_df["exec_ts"] = pd.to_datetime(merged["exec_ts"]).values
    series_df["spot_volume"] = pd.to_numeric(merged["spot_volume"], errors="coerce").fillna(0.0).values
    series_df["future_volume"] = pd.to_numeric(merged["future_volume"], errors="coerce").fillna(0.0).values

    replay = _apply_spread_carry_signals(
        series_df,
        merged=None,
        dividends=dividends,
        key_rates=key_rates,
        settings=settings,
        future_spec=future_spec,
        alpha_cfg=alpha_cfg,
    )

    action = replay["signal_action"].astype(str).str.lower() if "signal_action" in replay.columns else pd.Series([], dtype="string")
    entry_signals = int((action == "enter").sum())
    exit_signals = int((action == "exit").sum())
    exit_mask = replay["exit_flag"].fillna(False).astype(bool) if "exit_flag" in replay.columns else pd.Series(False, index=replay.index)
    closed_mask = exit_mask & replay["trade_return_annual_operational"].notna()
    trades_closed = int(closed_mask.sum())

    stats = _execution_quality_stats(replay)
    avg_fill = _avg_recent_trade_return_annual(replay)
    avg_oper = _avg_recent_trade_return_annual_operational(replay)
    entry_wait = replay.loc[closed_mask, "entry_wait_minutes"].dropna() if "entry_wait_minutes" in replay.columns else pd.Series(dtype=float)
    exit_wait = replay.loc[closed_mask, "exit_wait_minutes"].dropna() if "exit_wait_minutes" in replay.columns else pd.Series(dtype=float)

    elapsed = time.perf_counter() - started
    result = {
        "stock": pair.stock,
        "future": pair.future,
        "rows": int(len(replay)),
        "days": int(pd.Series(replay["date"]).nunique()) if "date" in replay.columns else 0,
        "entry_signals": entry_signals,
        "exit_signals": exit_signals,
        "trades_closed": trades_closed,
        "avg_trade_return_annual_fill_to_fill_last5": avg_fill,
        "avg_trade_return_annual_operational_last5": avg_oper,
        "share_target_pass": stats.get("share_target_pass"),
        "unfilled_entry_rate": stats.get("unfilled_entry_rate"),
        "unfilled_exit_rate": stats.get("unfilled_exit_rate"),
        "forced_exit_rate": stats.get("forced_exit_rate"),
        "avg_entry_wait_min_closed": float(entry_wait.mean()) if not entry_wait.empty else None,
        "avg_exit_wait_min_closed": float(exit_wait.mean()) if not exit_wait.empty else None,
        "elapsed_sec": round(elapsed, 2),
        "error": None,
    }

    if save_series_dir is not None:
        save_series_dir.mkdir(parents=True, exist_ok=True)
        replay.to_csv(save_series_dir / f"intraday_minute_series_{pair.stock}_{pair.future}.csv", index=False)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Intraday replay on all common minutes with causal execution lag.")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--pairs", default=None, help="Comma-separated STOCK:FUTURE list.")
    parser.add_argument("--from-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--till-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--lookback-days", type=int, default=120)
    parser.add_argument("--signal-exec-lag-days", type=int, default=0)
    parser.add_argument("--execution-lag-minutes", type=int, default=30)
    parser.add_argument("--execution-max-wait-minutes", type=int, default=30)
    parser.add_argument("--out-csv", default="data/output/intraday_minute_replay_30m.csv")
    parser.add_argument("--out-json", default="data/output/intraday_minute_replay_30m_summary.json")
    parser.add_argument("--save-series-dir", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    settings = settings.model_copy(deep=True)
    alpha = settings.spread_carry_alpha
    alpha.price_source = "common_minute_close"
    alpha.common_minute_anchor = "last"
    alpha.signal_exec_lag_days = max(int(args.signal_exec_lag_days), 0)
    alpha.execution_lag_minutes = max(int(args.execution_lag_minutes), 0)
    alpha.execution_max_wait_minutes = max(int(args.execution_max_wait_minutes), 1)

    today = date.today()
    till_date = _parse_date(args.till_date) if args.till_date else today
    from_date = _parse_date(args.from_date) if args.from_date else (till_date - timedelta(days=max(args.lookback_days, 1)))
    if from_date > till_date:
        raise SystemExit("from-date must be <= till-date")

    pairs = _parse_pairs(args.pairs)
    paths = resolve_paths(settings)
    dirs = _data_paths(paths.data_dir)
    future_specs = _load_future_specs(paths.data_dir)
    client = _build_client(settings)

    print(
        f"[intraday-minute] range={from_date.isoformat()}..{till_date.isoformat()} pairs={len(pairs)} "
        f"lag_days={alpha.signal_exec_lag_days} lag_min={alpha.execution_lag_minutes} wait_min={alpha.execution_max_wait_minutes}",
        flush=True,
    )

    save_series_dir = Path(args.save_series_dir) if args.save_series_dir else None
    rows: list[dict[str, object]] = []
    for idx, pair in enumerate(pairs, start=1):
        print(f"[intraday-minute] {idx}/{len(pairs)} {pair.stock}-{pair.future} start", flush=True)
        try:
            row = _run_pair(
                pair=pair,
                settings=settings,
                client=client,
                from_date=from_date,
                till_date=till_date,
                future_specs=future_specs,
                dirs=dirs,
                save_series_dir=save_series_dir,
            )
        except Exception as exc:  # noqa: BLE001 - continue batch if one pair fails
            row = {
                "stock": pair.stock,
                "future": pair.future,
                "rows": 0,
                "days": 0,
                "entry_signals": 0,
                "exit_signals": 0,
                "trades_closed": 0,
                "avg_trade_return_annual_fill_to_fill_last5": None,
                "avg_trade_return_annual_operational_last5": None,
                "share_target_pass": None,
                "unfilled_entry_rate": None,
                "unfilled_exit_rate": None,
                "forced_exit_rate": None,
                "avg_entry_wait_min_closed": None,
                "avg_exit_wait_min_closed": None,
                "elapsed_sec": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
        rows.append(row)
        print(
            f"[intraday-minute] {pair.stock}-{pair.future} rows={row['rows']} entries={row['entry_signals']} "
            f"exits={row['exit_signals']} closed={row['trades_closed']} avg_oper={row['avg_trade_return_annual_operational_last5']} "
            f"unfilled_entry={row['unfilled_entry_rate']} err={row['error']}",
            flush=True,
        )

    result_df = pd.DataFrame(rows)
    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(out_csv, index=False)

    valid = result_df[result_df["error"].isna()]
    summary = {
        "params": {
            "range": {"from": from_date.isoformat(), "till": till_date.isoformat()},
            "pairs": [f"{pair.stock}:{pair.future}" for pair in pairs],
            "signal_exec_lag_days": alpha.signal_exec_lag_days,
            "execution_lag_minutes": alpha.execution_lag_minutes,
            "execution_max_wait_minutes": alpha.execution_max_wait_minutes,
            "price_source": alpha.price_source,
            "common_minute_anchor": alpha.common_minute_anchor,
        },
        "files": {"csv": str(out_csv).replace("\\", "/")},
        "aggregate": {
            "pairs_total": int(len(result_df)),
            "pairs_ok": int(len(valid)),
            "pairs_failed": int(len(result_df) - len(valid)),
            "avg_oper_mean": (
                float(valid["avg_trade_return_annual_operational_last5"].dropna().mean())
                if not valid.empty
                else None
            ),
            "unfilled_entry_rate_mean": (
                float(valid["unfilled_entry_rate"].dropna().mean())
                if not valid.empty
                else None
            ),
            "forced_exit_rate_mean": (
                float(valid["forced_exit_rate"].dropna().mean())
                if not valid.empty
                else None
            ),
            "trades_closed_total": (
                int(pd.to_numeric(valid["trades_closed"], errors="coerce").fillna(0).sum())
                if not valid.empty
                else 0
            ),
        },
    }
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[intraday-minute] done csv={out_csv}", flush=True)
    print(f"[intraday-minute] done summary={out_json}", flush=True)


if __name__ == "__main__":
    main()
