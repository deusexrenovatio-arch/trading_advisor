from __future__ import annotations

import argparse
import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

from moex_carry.config import load_settings, resolve_paths
from moex_carry.data import MoexIssClient
from moex_carry.pipeline import _future_price_scale, _minute_close_frame, _parse_contract_specs


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _load_future_scale(data_dir: Path, future: str) -> float:
    futures_path = data_dir / "raw" / "futures.csv"
    if not futures_path.exists():
        raise SystemExit(f"Missing futures list: {futures_path}")
    futures_df = pd.read_csv(futures_path)
    specs = {spec.secid: spec for spec in _parse_contract_specs(futures_df)}
    spec = specs.get(future)
    if spec is None:
        raise SystemExit(f"Future {future} not found in {futures_path}")
    return _future_price_scale(spec)


def _daily_trading_days(
    client: MoexIssClient,
    *,
    engine: str,
    market: str,
    board: str,
    secid: str,
    from_date: date,
    till_date: date,
) -> list[date]:
    raw = client.get_candles(engine, market, secid, board, from_date, till_date, interval=24)
    df = pd.DataFrame(raw)
    if df.empty or "begin" not in df.columns:
        return []
    days = pd.to_datetime(df["begin"], errors="coerce").dt.date.dropna().drop_duplicates().tolist()
    days.sort()
    return days


def _calendar_days(from_date: date, till_date: date) -> list[date]:
    days: list[date] = []
    day = from_date
    while day <= till_date:
        days.append(day)
        day += timedelta(days=1)
    return days


def _daily_trading_days_resilient(
    client: MoexIssClient,
    *,
    engine: str,
    market: str,
    board: str,
    secid: str,
    from_date: date,
    till_date: date,
    chunk_days: int = 45,
) -> list[date]:
    try:
        direct = _daily_trading_days(
            client,
            engine=engine,
            market=market,
            board=board,
            secid=secid,
            from_date=from_date,
            till_date=till_date,
        )
        if direct:
            return direct
    except Exception as exc:  # noqa: BLE001 - resilience path
        print(
            f"[minute-export] {secid}: daily prefetch failed on full range, switching to chunk mode ({exc})",
            flush=True,
        )

    chunk = max(int(chunk_days), 1)
    day = from_date
    collected: list[date] = []
    while day <= till_date:
        chunk_end = min(day + timedelta(days=chunk - 1), till_date)
        try:
            part = _daily_trading_days(
                client,
                engine=engine,
                market=market,
                board=board,
                secid=secid,
                from_date=day,
                till_date=chunk_end,
            )
        except Exception as exc:  # noqa: BLE001 - continue export even on chunk failure
            print(
                f"[minute-export] {secid}: daily chunk {day.isoformat()}..{chunk_end.isoformat()} "
                f"failed, fallback to calendar days ({exc})",
                flush=True,
            )
            part = _calendar_days(day, chunk_end)
        if not part:
            part = _calendar_days(day, chunk_end)
        collected.extend(part)
        day = chunk_end + timedelta(days=1)

    dedup = sorted(set(collected))
    return dedup


def _read_existing(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["date", "ts", "price", "volume"])
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(columns=["date", "ts", "price", "volume"])
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    keep = [col for col in ["date", "ts", "price", "volume"] if col in df.columns]
    if len(keep) < 4:
        return pd.DataFrame(columns=["date", "ts", "price", "volume"])
    return df[keep].dropna(subset=["ts", "price"])


def _state_path(out_path: Path) -> Path:
    return out_path.with_suffix(out_path.suffix + ".state.json")


def _load_completed_days(path: Path) -> set[date]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - ignore broken state file and continue
        return set()
    days: set[date] = set()
    for raw in payload.get("completed_days", []):
        try:
            days.add(date.fromisoformat(str(raw)))
        except ValueError:
            continue
    return days


def _save_completed_days(path: Path, days: set[date]) -> None:
    payload = {"completed_days": sorted(day.isoformat() for day in days)}
    tmp = path.with_suffix(path.suffix + ".tmp")
    for _ in range(3):
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
            return
        except PermissionError:
            time.sleep(0.05)
            continue


def _save_frame(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(path)


def _fetch_leg_minutes(
    client: MoexIssClient,
    *,
    engine: str,
    market: str,
    board: str,
    secid: str,
    days: Iterable[date],
    price_scale: float,
    out_path: Path,
    resume: bool,
    progress_every: int,
) -> tuple[pd.DataFrame, list[dict[str, str]], int]:
    existing = _read_existing(out_path) if resume else pd.DataFrame(columns=["date", "ts", "price", "volume"])
    completed_days: set[date] = set(existing["date"].dropna().tolist()) if not existing.empty else set()
    state_file = _state_path(out_path)
    if resume:
        completed_days |= _load_completed_days(state_file)
    all_days = list(days)
    pending_days = [day for day in all_days if day not in completed_days]
    total = len(all_days)
    pending = len(pending_days)
    print(
        f"[minute-export] {secid}: trading_days={total}, resume_completed={len(completed_days)}, pending={pending}",
        flush=True,
    )

    frames: list[pd.DataFrame] = []
    errors: list[dict[str, str]] = []
    rows_accum = 0
    for idx, day in enumerate(pending_days, start=1):
        try:
            raw = client.get_candles(engine, market, secid, board, day, day, interval=1)
            day_df = _minute_close_frame(raw, price_scale=price_scale)
        except Exception as exc:  # noqa: BLE001 - export must continue on per-day errors
            errors.append({"day": day.isoformat(), "error": str(exc)})
            print(
                f"[minute-export] {secid}: {idx}/{pending} day={day.isoformat()} error={exc}",
                flush=True,
            )
            continue

        if not day_df.empty:
            frames.append(day_df)
            rows_accum += len(day_df)
        completed_days.add(day)
        _save_completed_days(state_file, completed_days)

        if idx == 1 or idx == pending or (progress_every > 0 and idx % progress_every == 0):
            print(
                f"[minute-export] {secid}: {idx}/{pending} day={day.isoformat()} rows_loaded={rows_accum}",
                flush=True,
            )

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["date", "ts", "price", "volume"])
    if existing.empty:
        merged = combined
    elif combined.empty:
        merged = existing.copy()
    else:
        merged = pd.concat([existing, combined], ignore_index=True)
    if merged.empty:
        result = pd.DataFrame(columns=["date", "ts", "price", "volume"])
    else:
        result = merged.sort_values("ts").drop_duplicates(subset=["ts"], keep="last")
        result["date"] = pd.to_datetime(result["ts"]).dt.date
        result = result[["date", "ts", "price", "volume"]]
    _save_frame(out_path, result)
    return result, errors, pending


def _common_daily_anchor(stock_df: pd.DataFrame, future_df: pd.DataFrame, anchor: str) -> pd.DataFrame:
    if stock_df.empty or future_df.empty:
        return pd.DataFrame(columns=["date", "spot", "future", "spot_volume", "future_volume", "exec_ts"])
    joined = stock_df.merge(future_df, on="ts", how="inner", suffixes=("_stock", "_future"))
    if joined.empty:
        return pd.DataFrame(columns=["date", "spot", "future", "spot_volume", "future_volume", "exec_ts"])
    joined = joined.sort_values("ts")
    joined["date"] = pd.to_datetime(joined["ts"]).dt.date
    per_day_vol = (
        stock_df.groupby("date", as_index=False)["volume"].sum().rename(columns={"volume": "spot_volume"})
    ).merge(
        future_df.groupby("date", as_index=False)["volume"].sum().rename(columns={"volume": "future_volume"}),
        on="date",
        how="inner",
    )
    selected = joined.groupby("date", as_index=False).head(1) if anchor == "first" else joined.groupby("date", as_index=False).tail(1)
    selected = selected.merge(per_day_vol, on="date", how="left")
    selected = selected.rename(columns={"price_stock": "spot", "price_future": "future", "ts": "exec_ts"})
    selected = selected[["date", "spot", "future", "spot_volume", "future_volume", "exec_ts"]]
    return selected.sort_values("date").drop_duplicates(subset=["date"], keep="last")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export minute candles for a stock-future pair with resume and progress.")
    parser.add_argument("--stock", required=True, help="Stock secid, e.g. FLOT")
    parser.add_argument("--future", required=True, help="Future secid, e.g. FLH6")
    parser.add_argument("--from-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--till-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--out-dir", default="data/output/minute")
    parser.add_argument("--anchor", choices=["first", "last"], default="last")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--progress-every", type=int, default=5)
    parser.add_argument("--timeout-sec", type=int, default=None)
    parser.add_argument("--max-retries", type=int, default=None)
    parser.add_argument("--retry-backoff-sec", type=float, default=None)
    parser.add_argument("--retry-max-backoff-sec", type=float, default=None)
    parser.add_argument("--disable-fallback", action="store_true")
    args = parser.parse_args()

    start_ts = time.perf_counter()
    settings = load_settings(args.config)
    paths = resolve_paths(settings)
    data_dir = paths.data_dir
    from_date = _parse_date(args.from_date)
    till_date = _parse_date(args.till_date)
    if from_date > till_date:
        raise SystemExit("from-date must be <= till-date")

    timeout_sec = int(args.timeout_sec if args.timeout_sec is not None else settings.moex.request_timeout_sec)
    max_retries = int(args.max_retries if args.max_retries is not None else settings.moex.request_max_retries)
    retry_backoff_sec = float(
        args.retry_backoff_sec if args.retry_backoff_sec is not None else settings.moex.request_retry_backoff_sec
    )
    retry_max_backoff_sec = float(
        args.retry_max_backoff_sec
        if args.retry_max_backoff_sec is not None
        else settings.moex.request_retry_max_backoff_sec
    )
    fallback_ips = [] if args.disable_fallback else list(settings.moex.fallback_ips or [])

    client = MoexIssClient(
        settings.moex.base_url,
        timeout_sec,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        retry_max_backoff_sec=retry_max_backoff_sec,
        fallback_ips=fallback_ips,
        force_fallback=bool(settings.moex.force_fallback and fallback_ips),
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stock_path = out_dir / f"{args.stock}_{settings.moex.shares_board}_1m_{args.from_date}_{args.till_date}.csv"
    future_path = out_dir / f"{args.future}_{settings.moex.futures_board}_1m_{args.from_date}_{args.till_date}.csv"
    common_path = out_dir / f"{args.stock}_{args.future}_common_1m_{args.from_date}_{args.till_date}.csv"
    summary_path = out_dir / f"export_summary_{args.stock}_{args.future}_{args.from_date}_{args.till_date}.json"

    print(
        f"[minute-export] pair={args.stock}-{args.future} range={args.from_date}..{args.till_date} "
        f"resume={args.resume} anchor={args.anchor}",
        flush=True,
    )
    print(
        f"[minute-export] transport timeout={timeout_sec}s retries={max_retries} "
        f"backoff={retry_backoff_sec}/{retry_max_backoff_sec} fallback_ips={len(fallback_ips)}",
        flush=True,
    )

    stock_days = _daily_trading_days_resilient(
        client,
        engine=settings.moex.engine_shares,
        market=settings.moex.market_shares,
        board=settings.moex.shares_board,
        secid=args.stock,
        from_date=from_date,
        till_date=till_date,
    )
    future_days = _daily_trading_days_resilient(
        client,
        engine=settings.moex.engine_futures,
        market=settings.moex.market_futures,
        board=settings.moex.futures_board,
        secid=args.future,
        from_date=from_date,
        till_date=till_date,
    )
    future_scale = _load_future_scale(data_dir, args.future)

    stock_df, stock_errors, stock_pending = _fetch_leg_minutes(
        client,
        engine=settings.moex.engine_shares,
        market=settings.moex.market_shares,
        board=settings.moex.shares_board,
        secid=args.stock,
        days=stock_days,
        price_scale=1.0,
        out_path=stock_path,
        resume=args.resume,
        progress_every=max(int(args.progress_every), 1),
    )
    future_df, future_errors, future_pending = _fetch_leg_minutes(
        client,
        engine=settings.moex.engine_futures,
        market=settings.moex.market_futures,
        board=settings.moex.futures_board,
        secid=args.future,
        days=future_days,
        price_scale=future_scale,
        out_path=future_path,
        resume=args.resume,
        progress_every=max(int(args.progress_every), 1),
    )

    common_df = _common_daily_anchor(stock_df, future_df, args.anchor)
    _save_frame(common_path, common_df)

    elapsed = time.perf_counter() - start_ts
    summary = {
        "pair": f"{args.stock}-{args.future}",
        "from": args.from_date,
        "till": args.till_date,
        "anchor": args.anchor,
        "resume": bool(args.resume),
        "request": {
            "timeout_sec": timeout_sec,
            "max_retries": max_retries,
            "retry_backoff_sec": retry_backoff_sec,
            "retry_max_backoff_sec": retry_max_backoff_sec,
            "fallback_ips_count": len(fallback_ips),
        },
        "trading_days": {
            "stock": len(stock_days),
            "future": len(future_days),
            "stock_pending": stock_pending,
            "future_pending": future_pending,
        },
        "rows": {
            "stock": int(len(stock_df)),
            "future": int(len(future_df)),
            "common": int(len(common_df)),
        },
        "files": {
            "stock": str(stock_path).replace("\\", "/"),
            "future": str(future_path).replace("\\", "/"),
            "common": str(common_path).replace("\\", "/"),
        },
        "errors": {
            "stock_count": len(stock_errors),
            "future_count": len(future_errors),
            "stock": stock_errors,
            "future": future_errors,
        },
        "future_scale_per_share": float(future_scale),
        "elapsed_sec": elapsed,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[minute-export] done in {elapsed:.1f}s "
        f"rows(stock={len(stock_df)}, future={len(future_df)}, common={len(common_df)})",
        flush=True,
    )
    print(f"[minute-export] summary={summary_path}", flush=True)


if __name__ == "__main__":
    main()
