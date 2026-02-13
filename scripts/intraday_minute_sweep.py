from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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


PRELOAD_CACHE_SCHEMA_VERSION = 1
PRELOAD_CACHE_MODES = {"off", "readwrite", "readonly", "refresh"}


def _parse_pairs(value: str | None) -> list[Pair]:
    if not value:
        return list(DEFAULT_PAIRS)
    items: list[Pair] = []
    for raw in value.split(","):
        text = raw.strip()
        if not text:
            continue
        if ":" not in text:
            raise ValueError(f"Invalid pair format '{text}', expected STOCK:FUTURE")
        stock, future = text.split(":", 1)
        items.append(Pair(stock.strip().upper(), future.strip().upper()))
    if not items:
        raise ValueError("No pairs provided")
    return items


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "t"}:
        return True
    if text in {"0", "false", "no", "n", "f", ""}:
        return False
    try:
        return float(text) != 0.0
    except Exception:
        return False


def _load_liquidity_flags(
    *,
    path: Path | None,
    column: str,
) -> tuple[dict[tuple[str, str], bool], list[str]]:
    if path is None:
        return {}, []
    if not path.exists():
        return {}, [f"front_filter: liquidity_csv_not_found={path}"]
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return {}, [f"front_filter: liquidity_csv_read_failed={path} ({exc})"]
    required = {"stock", "future", column}
    if not required.issubset(set(frame.columns)):
        return (
            {},
            [
                "front_filter: liquidity_csv_missing_columns="
                f"{path} required={sorted(required)}"
            ],
        )
    flags: dict[tuple[str, str], bool] = {}
    for row in frame.itertuples(index=False):
        stock = str(getattr(row, "stock", "")).strip().upper()
        future = str(getattr(row, "future", "")).strip().upper()
        if not stock or not future:
            continue
        raw = getattr(row, column, None)
        flags[(stock, future)] = _as_bool(raw)
    return flags, []


def select_front_pairs(
    *,
    settings: AppSettings,
    pairs: list[Pair],
    asof_date: date,
    roll_days: int = 7,
    liquidity_csv: Path | None = None,
    liquidity_column: str = "liquidity_pass",
) -> tuple[list[Pair], list[str]]:
    warnings: list[str] = []
    if not pairs:
        return [], warnings

    paths = resolve_paths(settings)
    future_specs = _load_future_specs(paths.data_dir)
    liquidity_flags, liq_warnings = _load_liquidity_flags(path=liquidity_csv, column=liquidity_column)
    warnings.extend(liq_warnings)

    stock_order: list[str] = []
    by_stock: dict[str, list[Pair]] = {}
    for pair in pairs:
        if pair.stock not in by_stock:
            stock_order.append(pair.stock)
            by_stock[pair.stock] = []
        if pair not in by_stock[pair.stock]:
            by_stock[pair.stock].append(pair)

    selected: list[Pair] = []
    min_roll_days = max(int(roll_days), 0)
    has_liquidity_data = bool(liquidity_flags)
    for stock in stock_order:
        candidates: list[dict[str, object]] = []
        for pair in by_stock[stock]:
            spec = future_specs.get(pair.future)
            if spec is None:
                warnings.append(f"front_filter: {pair.stock}-{pair.future} future_spec_not_found")
                continue
            dte = int((spec.expiry - asof_date).days)
            candidates.append(
                {
                    "pair": pair,
                    "expiry": spec.expiry,
                    "dte": dte,
                    "liquidity_pass": liquidity_flags.get((pair.stock, pair.future)),
                }
            )
        if not candidates:
            warnings.append(f"front_filter: {stock} no_valid_futures")
            continue
        candidates.sort(key=lambda item: (item["expiry"], item["pair"].future))

        pool = [item for item in candidates if int(item["dte"]) >= min_roll_days]
        if not pool:
            pool = [item for item in candidates if int(item["dte"]) >= 0]
            if not pool:
                pool = candidates
                warnings.append(
                    f"front_filter: {stock} no_nonexpired_futures_asof={asof_date.isoformat()}"
                )
            else:
                warnings.append(
                    f"front_filter: {stock} rolled_due_to_dte_lt_{min_roll_days}"
                )

        if has_liquidity_data:
            liquid_pool = [item for item in pool if item["liquidity_pass"] is True]
            if liquid_pool:
                pool = liquid_pool
            else:
                warnings.append(
                    f"front_filter: {stock} no_liquid_candidate_in_pool column={liquidity_column}"
                )

        chosen = pool[0]
        selected.append(chosen["pair"])
        if int(chosen["dte"]) < min_roll_days:
            warnings.append(
                f"front_filter: {stock} selected_{chosen['pair'].future}_dte={chosen['dte']}"
            )
    return selected, warnings


def _parse_int_grid(value: str) -> list[int]:
    result: list[int] = []
    for raw in value.split(","):
        text = raw.strip()
        if not text:
            continue
        result.append(int(text))
    if not result:
        raise ValueError("Integer grid is empty")
    return result


def _parse_float_grid(value: str) -> list[float]:
    result: list[float] = []
    for raw in value.split(","):
        text = raw.strip()
        if not text:
            continue
        result.append(float(text))
    if not result:
        raise ValueError("Float grid is empty")
    return result


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _normalize_preload_cache_mode(value: str) -> str:
    mode = str(value or "off").strip().lower()
    if mode not in PRELOAD_CACHE_MODES:
        raise ValueError(
            f"Invalid preload cache mode '{value}'. Expected one of: {sorted(PRELOAD_CACHE_MODES)}"
        )
    return mode


def _alpha_signature(settings: AppSettings) -> str:
    alpha = settings.spread_carry_alpha
    return "|".join(
        [
            f"price_source={getattr(alpha, 'price_source', '')}",
            f"anchor={getattr(alpha, 'common_minute_anchor', '')}",
            f"r_disc_annual={getattr(alpha, 'r_disc_annual', '')}",
            f"day_count={getattr(alpha, 'day_count', '')}",
            f"signal_exec_lag_days={getattr(alpha, 'signal_exec_lag_days', '')}",
        ]
    )


def _preload_cache_file(
    *,
    cache_dir: Path,
    pair: Pair,
    from_date: date,
    till_date: date,
    alpha_signature: str,
) -> Path:
    digest = hashlib.sha1(alpha_signature.encode("utf-8")).hexdigest()[:12]
    name = (
        f"{pair.stock}_{pair.future}_"
        f"{from_date.isoformat()}_{till_date.isoformat()}_{digest}.pkl"
    )
    return cache_dir / name


def _load_preload_cache(path: Path) -> dict[str, object] | None:
    try:
        payload = pd.read_pickle(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("schema_version", -1)) != PRELOAD_CACHE_SCHEMA_VERSION:
        return None
    series_base = payload.get("series_base")
    if not isinstance(series_base, pd.DataFrame) or series_base.empty:
        return None
    dividends = payload.get("dividends")
    if dividends is None:
        dividends = []
    if not isinstance(dividends, list):
        return None
    return payload


def _save_preload_cache(path: Path, payload: dict[str, object]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        pd.to_pickle(payload, temp_path)
        temp_path.replace(path)
        return True
    except Exception:
        return False


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
    minute_chunk_days: int = 10,
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
        chunk_days=max(int(minute_chunk_days), 1),
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
        chunk_days=max(int(minute_chunk_days), 1),
    )
    if stock_df.empty or future_df.empty:
        return pd.DataFrame(columns=["date", "spot", "future", "spot_volume", "future_volume", "exec_ts"])

    joined = stock_df.merge(future_df, on="ts", how="inner", suffixes=("_stock", "_future"))
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


def _apply_day_cutoff(df: pd.DataFrame, cutoff_minutes: int) -> pd.DataFrame:
    if df.empty or cutoff_minutes <= 0:
        return df.copy()
    work = df.copy()
    work["exec_ts"] = pd.to_datetime(work["exec_ts"])
    last_ts = work.groupby("date", as_index=False)["exec_ts"].max().rename(columns={"exec_ts": "day_last_ts"})
    work = work.merge(last_ts, on="date", how="left")
    work["keep_until"] = work["day_last_ts"] - pd.to_timedelta(int(cutoff_minutes), unit="m")
    filtered = work[work["exec_ts"] <= work["keep_until"]].copy()
    filtered = filtered.drop(columns=["day_last_ts", "keep_until"])
    return filtered.reset_index(drop=True)


def _prepare_pair_cache(
    *,
    settings: AppSettings,
    pairs: list[Pair],
    from_date: date,
    till_date: date,
    preload_cache_dir: Path | None = None,
    preload_cache_mode: str = "off",
    minute_chunk_days: int = 10,
    preload_workers: int = 1,
) -> tuple[list[dict[str, object]], list[str]]:
    paths = resolve_paths(settings)
    dirs = _data_paths(paths.data_dir)
    future_specs = _load_future_specs(paths.data_dir)
    key_rates = _load_key_rates(dirs["raw"] / "key_rates.csv")
    alpha_sig = _alpha_signature(settings)
    cache_mode = _normalize_preload_cache_mode(preload_cache_mode)
    cache_dir = preload_cache_dir
    if cache_mode != "off":
        if cache_dir is None:
            cache_mode = "off"
        else:
            cache_dir.mkdir(parents=True, exist_ok=True)
    cache_read_enabled = cache_mode in {"readwrite", "readonly"}
    cache_write_enabled = cache_mode in {"readwrite", "refresh"}
    cache_force_refresh = cache_mode == "refresh"

    cache: list[dict[str, object]] = []
    errors: list[str] = []
    cache_hits = 0
    cache_misses = 0
    cache_writes = 0
    cache_read_errors = 0
    miss_tasks: list[dict[str, object]] = []
    for idx, pair in enumerate(pairs, start=1):
        t0 = time.perf_counter()
        print(f"[sweep] preload {idx}/{len(pairs)} {pair.stock}-{pair.future} ...", flush=True)
        spec = future_specs.get(pair.future)
        if spec is None:
            errors.append(f"{pair.stock}-{pair.future}: future_spec_not_found")
            continue
        cache_file: Path | None = None
        if cache_dir is not None and cache_mode != "off":
            cache_file = _preload_cache_file(
                cache_dir=cache_dir,
                pair=pair,
                from_date=from_date,
                till_date=till_date,
                alpha_signature=alpha_sig,
            )
        if (
            cache_file is not None
            and cache_read_enabled
            and not cache_force_refresh
            and cache_file.exists()
        ):
            cached = _load_preload_cache(cache_file)
            if cached is not None:
                spread_series = cached["series_base"]
                dividends = cached.get("dividends", [])
                cache_hits += 1
                elapsed = time.perf_counter() - t0
                print(
                    f"[sweep] preload {pair.stock}-{pair.future} cache_hit "
                    f"rows={len(spread_series)} days={spread_series['date'].nunique()} ({elapsed:.1f}s)",
                    flush=True,
                )
                cache.append(
                    {
                        "pair": pair,
                        "future_spec": spec,
                        "dividends": dividends,
                        "key_rates": key_rates,
                        "series_base": spread_series,
                    }
                )
                continue
            cache_read_errors += 1
        if cache_mode == "readonly":
            errors.append(f"{pair.stock}-{pair.future}: preload_cache_miss_readonly")
            continue
        if cache_mode != "off":
            cache_misses += 1
        miss_tasks.append(
            {
                "pair": pair,
                "future_spec": spec,
                "cache_file": cache_file,
            }
        )

    def _load_miss_task(task: dict[str, object]) -> dict[str, object]:
        pair: Pair = task["pair"]  # type: ignore[assignment]
        spec = task["future_spec"]
        t0 = time.perf_counter()
        client = _build_client(settings)
        try:
            future_scale = _future_price_scale(spec)
            merged = _fetch_common_minute_rows(
                client=client,
                settings=settings,
                stock=pair.stock,
                future=pair.future,
                from_date=from_date,
                till_date=till_date,
                future_scale=future_scale,
                minute_chunk_days=minute_chunk_days,
            )
            if merged.empty:
                return {"task": task, "error": "no_common_minutes", "elapsed": time.perf_counter() - t0}

            dividends = _load_dividends(client, pair.stock, paths.data_dir)
            alpha = settings.spread_carry_alpha
            prices = merged[["date", "spot", "future"]].rename(columns={"future": "future_price"})
            spread_series = compute_spread_series(
                prices,
                spec.expiry,
                dividends,
                key_rates,
                r_disc_annual=alpha.r_disc_annual,
                day_count=alpha.day_count,
            )
            if spread_series.empty:
                return {"task": task, "error": "empty_spread_series", "elapsed": time.perf_counter() - t0}

            spread_series["exec_ts"] = pd.to_datetime(merged["exec_ts"]).values
            spread_series["spot_volume"] = pd.to_numeric(merged["spot_volume"], errors="coerce").fillna(0.0).values
            spread_series["future_volume"] = pd.to_numeric(merged["future_volume"], errors="coerce").fillna(0.0).values
            return {
                "task": task,
                "error": None,
                "series_base": spread_series,
                "dividends": dividends,
                "elapsed": time.perf_counter() - t0,
            }
        except Exception as exc:
            return {"task": task, "error": f"preload_failed ({exc})", "elapsed": time.perf_counter() - t0}

    workers = max(int(preload_workers), 1)
    if workers <= 1:
        miss_results = [_load_miss_task(task) for task in miss_tasks]
    else:
        miss_results = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(_load_miss_task, task): task for task in miss_tasks}
            for future in as_completed(future_map):
                miss_results.append(future.result())

    for result in miss_results:
        task = result["task"]
        pair: Pair = task["pair"]  # type: ignore[assignment]
        spec = task["future_spec"]
        error = result.get("error")
        if error:
            errors.append(f"{pair.stock}-{pair.future}: {error}")
            continue
        spread_series = result["series_base"]
        dividends = result.get("dividends", [])
        cache_file = task.get("cache_file")
        if isinstance(cache_file, Path) and cache_write_enabled:
            payload = {
                "schema_version": PRELOAD_CACHE_SCHEMA_VERSION,
                "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "pair": {"stock": pair.stock, "future": pair.future},
                "range": {"from": from_date.isoformat(), "till": till_date.isoformat()},
                "alpha_signature": alpha_sig,
                "series_base": spread_series,
                "dividends": dividends,
            }
            if _save_preload_cache(cache_file, payload):
                cache_writes += 1
        elapsed = float(result.get("elapsed", 0.0))
        print(
            f"[sweep] preload {pair.stock}-{pair.future} rows={len(spread_series)} "
            f"days={spread_series['date'].nunique()} ({elapsed:.1f}s)",
            flush=True,
        )
        cache.append(
            {
                "pair": pair,
                "future_spec": spec,
                "dividends": dividends,
                "key_rates": key_rates,
                "series_base": spread_series,
            }
        )
    if cache_mode != "off":
        print(
            "[sweep] preload cache stats: "
            f"mode={cache_mode} hits={cache_hits} misses={cache_misses} "
            f"writes={cache_writes} read_errors={cache_read_errors}",
            flush=True,
        )
    return cache, errors


def _run_scenario_on_pair(
    *,
    base_series: pd.DataFrame,
    cutoff_minutes: int,
    settings: AppSettings,
    future_spec: object,
    dividends: list[object],
    key_rates: list[object],
) -> dict[str, object]:
    series = _apply_day_cutoff(base_series, cutoff_minutes)
    if series.empty:
        return {
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
            "error": "series_empty_after_cutoff",
        }

    replay = _apply_spread_carry_signals(
        series,
        merged=None,
        dividends=dividends,
        key_rates=key_rates,
        settings=settings,
        future_spec=future_spec,
        alpha_cfg=settings.spread_carry_alpha,
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
    return {
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
        "error": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep intraday minute replay params to reduce unfilled/forced metrics.")
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
    parser.add_argument("--signal-exec-lag-days", type=int, default=0)
    parser.add_argument("--execution-lag-grid", default="15,30")
    parser.add_argument("--execution-wait-grid", default="30,60,120,240")
    parser.add_argument("--entry-tolerance-grid", default="0.0015,0.003,0.005,0.01")
    parser.add_argument("--cutoff-minutes-grid", default="0,30,60")
    parser.add_argument(
        "--minute-chunk-days",
        type=int,
        default=21,
        help="Calendar days per chunk for minute-candle fetch.",
    )
    parser.add_argument(
        "--preload-cache-mode",
        default="readwrite",
        choices=sorted(PRELOAD_CACHE_MODES),
        help="Preload cache mode for pair minute-series preparation.",
    )
    parser.add_argument("--preload-workers", type=int, default=1, help="Parallel workers for cache preload misses.")
    parser.add_argument(
        "--preload-cache-dir",
        default="data/output/intraday_preload_cache",
        help="Directory for preload cache files.",
    )
    parser.add_argument("--out-pairs-csv", default="data/output/intraday_minute_sweep_pairs.csv")
    parser.add_argument("--out-summary-csv", default="data/output/intraday_minute_sweep_summary.csv")
    parser.add_argument("--out-summary-json", default="data/output/intraday_minute_sweep_summary.json")
    args = parser.parse_args()

    settings_base = load_settings(args.config)
    settings_base = settings_base.model_copy(deep=True)
    settings_base.spread_carry_alpha.price_source = "common_minute_close"
    settings_base.spread_carry_alpha.common_minute_anchor = "last"
    settings_base.spread_carry_alpha.signal_exec_lag_days = max(int(args.signal_exec_lag_days), 0)

    pairs = _parse_pairs(args.pairs)
    execution_lag_grid = _parse_int_grid(args.execution_lag_grid)
    execution_wait_grid = _parse_int_grid(args.execution_wait_grid)
    entry_tolerance_grid = _parse_float_grid(args.entry_tolerance_grid)
    cutoff_grid = _parse_int_grid(args.cutoff_minutes_grid)

    today = date.today()
    till_date = _parse_date(args.till_date) if args.till_date else today
    from_date = _parse_date(args.from_date) if args.from_date else (till_date - timedelta(days=max(args.lookback_days, 1)))
    if from_date > till_date:
        raise SystemExit("from-date must be <= till-date")
    front_warnings: list[str] = []
    if args.front_only:
        front_asof = _parse_date(args.front_asof_date) if args.front_asof_date else till_date
        pairs, front_warnings = select_front_pairs(
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
        f"[sweep] range={from_date.isoformat()}..{till_date.isoformat()} pairs={len(pairs)} "
        f"lag_days={settings_base.spread_carry_alpha.signal_exec_lag_days}",
        flush=True,
    )
    if args.front_only:
        print(
            f"[sweep] front_only enabled roll_days={max(int(args.front_roll_days), 0)} "
            f"asof={(args.front_asof_date or till_date.isoformat())} pairs={len(pairs)}",
            flush=True,
        )
        if front_warnings:
            print(f"[sweep] front_only warnings: {front_warnings}", flush=True)
    print(
        f"[sweep] grid: lag={execution_lag_grid} wait={execution_wait_grid} tol={entry_tolerance_grid} cutoff={cutoff_grid}",
        flush=True,
    )
    print(
        f"[sweep] preload_cache mode={args.preload_cache_mode} dir={args.preload_cache_dir}",
        flush=True,
    )
    print(f"[sweep] preload_workers={max(int(args.preload_workers), 1)}", flush=True)
    print(f"[sweep] minute_chunk_days={max(int(args.minute_chunk_days), 1)}", flush=True)
    print(f"[sweep] pair_workers={max(int(args.pair_workers), 1)}", flush=True)

    cache, preload_errors = _prepare_pair_cache(
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
        print(f"[sweep] preload warnings: {preload_errors}", flush=True)

    combos = list(itertools.product(execution_lag_grid, execution_wait_grid, entry_tolerance_grid, cutoff_grid))
    print(f"[sweep] scenarios={len(combos)}", flush=True)

    pair_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []

    for idx, (lag_min, wait_min, tol, cutoff) in enumerate(combos, start=1):
        t0 = time.perf_counter()
        settings = settings_base.model_copy(deep=True)
        alpha = settings.spread_carry_alpha
        alpha.execution_lag_minutes = max(int(lag_min), 0)
        alpha.execution_max_wait_minutes = max(int(wait_min), 1)
        alpha.entry_price_tolerance_pct = max(float(tol), 0.0)
        scenario_id = f"lag{lag_min}_wait{wait_min}_tol{tol:.6f}_cut{cutoff}"
        print(f"[sweep] {idx}/{len(combos)} {scenario_id}", flush=True)

        scenario_pair_rows: list[dict[str, object]] = []
        def _eval_item(item: dict[str, object]) -> dict[str, object]:
            pair = item["pair"]
            metrics = _run_scenario_on_pair(
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
                "entry_price_tolerance_pct": float(tol),
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
        avg_oper = valid["avg_trade_return_annual_operational_last5"].dropna()
        unfilled = valid["unfilled_entry_rate"].dropna()
        forced = valid["forced_exit_rate"].dropna()
        closed_total = int(pd.to_numeric(valid["trades_closed"], errors="coerce").fillna(0).sum()) if not valid.empty else 0
        summary_row = {
            "scenario_id": scenario_id,
            "execution_lag_minutes": int(lag_min),
            "execution_max_wait_minutes": int(wait_min),
            "entry_price_tolerance_pct": float(tol),
            "signal_cutoff_before_day_end_minutes": int(cutoff),
            "pairs_total": int(len(frame)),
            "pairs_ok": int(len(valid)),
            "pairs_failed": int(len(frame) - len(valid)),
            "avg_oper_mean": float(avg_oper.mean()) if not avg_oper.empty else None,
            "unfilled_entry_rate_mean": float(unfilled.mean()) if not unfilled.empty else None,
            "forced_exit_rate_mean": float(forced.mean()) if not forced.empty else None,
            "trades_closed_total": closed_total,
            "objective_fill_forced_sum": (
                (float(unfilled.mean()) if not unfilled.empty else 10.0)
                + (float(forced.mean()) if not forced.empty else 10.0)
            ),
            "elapsed_sec": round(time.perf_counter() - t0, 2),
        }
        summary_rows.append(summary_row)
        print(
            f"[sweep] {scenario_id} -> unfilled={summary_row['unfilled_entry_rate_mean']} "
            f"forced={summary_row['forced_exit_rate_mean']} avg_oper={summary_row['avg_oper_mean']} closed={closed_total}",
            flush=True,
        )

    pair_df = pd.DataFrame(pair_rows)
    summary_df = pd.DataFrame(summary_rows)
    summary_df = summary_df.sort_values(
        ["objective_fill_forced_sum", "unfilled_entry_rate_mean", "forced_exit_rate_mean", "avg_oper_mean"],
        ascending=[True, True, True, False],
    ).reset_index(drop=True)

    out_pairs = Path(args.out_pairs_csv)
    out_summary = Path(args.out_summary_csv)
    out_json = Path(args.out_summary_json)
    out_pairs.parent.mkdir(parents=True, exist_ok=True)
    pair_df.to_csv(out_pairs, index=False)
    summary_df.to_csv(out_summary, index=False)

    top = summary_df.head(10).to_dict(orient="records")
    payload = {
        "params": {
            "range": {"from": from_date.isoformat(), "till": till_date.isoformat()},
            "pairs": [f"{pair.stock}:{pair.future}" for pair in pairs],
            "signal_exec_lag_days": settings_base.spread_carry_alpha.signal_exec_lag_days,
            "execution_lag_grid": execution_lag_grid,
            "execution_wait_grid": execution_wait_grid,
            "entry_tolerance_grid": entry_tolerance_grid,
            "cutoff_minutes_grid": cutoff_grid,
            "minute_chunk_days": max(int(args.minute_chunk_days), 1),
            "pair_workers": max(int(args.pair_workers), 1),
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
        "top10": top,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[sweep] done pairs={out_pairs}", flush=True)
    print(f"[sweep] done summary={out_summary}", flush=True)
    print(f"[sweep] done top10={out_json}", flush=True)


if __name__ == "__main__":
    main()
