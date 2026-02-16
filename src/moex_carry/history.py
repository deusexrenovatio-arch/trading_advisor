from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests

from moex_carry.config import AppSettings, resolve_paths
from moex_carry.data import MoexIssClient

STATE_VERSION = 1
DEFAULT_START_DATE = date(2010, 1, 1)


def collect_history(
    settings: AppSettings,
    kind: str = "both",
    symbols_per_run: int = 20,
    max_days_per_run: int = 60,
    chunk_days: int = 30,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    sleep_sec: float = 0.2,
    retries: int = 3,
    retry_backoff_sec: float = 2.0,
) -> None:
    paths = resolve_paths(settings)
    history_dir = _ensure_history_dir(paths.data_dir)
    state_path = history_dir / "state.json"
    state = _load_state(state_path)

    if start_date is None:
        start_date = DEFAULT_START_DATE
    if end_date is None:
        end_date = date.today()

    kinds = _normalize_kinds(kind)
    client = MoexIssClient(
        settings.moex.base_url,
        settings.moex.request_timeout_sec,
        max_retries=settings.moex.request_max_retries,
        retry_backoff_sec=settings.moex.request_retry_backoff_sec,
        retry_max_backoff_sec=settings.moex.request_retry_max_backoff_sec,
        fallback_ips=settings.moex.fallback_ips,
        force_fallback=settings.moex.force_fallback,
    )

    for dataset in kinds:
        secids = _load_or_fetch_secids(dataset, paths.data_dir, client, settings)
        if not secids:
            print(f"[history] No securities for {dataset}, skipping.", flush=True)
            continue

        selected, next_index = _select_symbols(
            secids,
            state["list_index"].get(dataset, 0),
            symbols_per_run,
        )
        state["list_index"][dataset] = next_index
        _save_state(state_path, state)

        board = _board_for_kind(settings, dataset)
        engine = _engine_for_kind(settings, dataset)
        market = _market_for_kind(settings, dataset)
        candles_dir = _candles_dir(history_dir, dataset)

        for secid in selected:
            cursor = _parse_date(state["cursor"][dataset].get(secid))
            current = start_date if cursor is None else max(start_date, cursor + timedelta(days=1))
            if current > end_date:
                continue

            run_end = _cap_end_date(current, end_date, max_days_per_run)
            last_written = _read_last_date(candles_dir / f"{secid}.csv")

            while current <= run_end:
                chunk_end = _cap_end_date(current, run_end, chunk_days)
                raw = _get_candles_with_retry(
                    client,
                    engine=engine,
                    market=market,
                    board=board,
                    secid=secid,
                    from_date=current,
                    till_date=chunk_end,
                    retries=retries,
                    retry_backoff_sec=retry_backoff_sec,
                )
                df = _normalize_candles(raw)
                if not df.empty:
                    if last_written is not None:
                        df = df[df["date"] > last_written]
                    if not df.empty:
                        _append_candles(candles_dir / f"{secid}.csv", df)
                        last_written = max(df["date"])

                state["cursor"][dataset][secid] = chunk_end.isoformat()
                _save_state(state_path, state)

                current = chunk_end + timedelta(days=1)
                if sleep_sec > 0:
                    time.sleep(sleep_sec)

        print(
            f"[history] {dataset} batch done: {len(selected)} symbols, next index {next_index}.",
            flush=True,
        )


def _ensure_history_dir(base_dir: Path) -> Path:
    history_dir = base_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir


def _candles_dir(history_dir: Path, dataset: str) -> Path:
    path = history_dir / "candles" / dataset
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_state() -> dict:
    return {
        "version": STATE_VERSION,
        "list_index": {"shares": 0, "futures": 0},
        "cursor": {"shares": {}, "futures": {}},
    }


def _load_state(path: Path) -> dict:
    if not path.exists():
        return _default_state()
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return _default_state()

    state = _default_state()
    state.update({k: v for k, v in data.items() if k in state})
    state["list_index"].update(data.get("list_index", {}))
    state["cursor"]["shares"].update(data.get("cursor", {}).get("shares", {}))
    state["cursor"]["futures"].update(data.get("cursor", {}).get("futures", {}))
    return state


def _save_state(path: Path, state: dict) -> None:
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=True, indent=2)
    tmp_path.replace(path)


def _normalize_kinds(kind: str) -> list[str]:
    normalized = kind.lower().strip()
    if normalized == "both":
        return ["shares", "futures"]
    if normalized in {"shares", "futures"}:
        return [normalized]
    raise ValueError(f"Unsupported history kind: {kind}")


def _select_symbols(secids: list[str], start_index: int, count: int) -> tuple[list[str], int]:
    total = len(secids)
    if total == 0:
        return [], 0
    if count <= 0 or count >= total:
        return secids, 0
    start_index = start_index % total
    end_index = start_index + count
    if end_index <= total:
        return secids[start_index:end_index], end_index if end_index < total else 0
    wrap = end_index - total
    return secids[start_index:] + secids[:wrap], wrap


def _load_or_fetch_secids(
    dataset: str, data_dir: Path, client: MoexIssClient, settings: AppSettings
) -> list[str]:
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / ("shares.csv" if dataset == "shares" else "futures.csv")

    if path.exists():
        df = pd.read_csv(path)
    else:
        if dataset == "shares":
            rows = list(
                client.iter_securities(
                    settings.moex.engine_shares,
                    settings.moex.market_shares,
                    settings.moex.shares_board,
                )
            )
        else:
            rows = client.get_futures_specs(settings.moex.futures_board)
        df = pd.DataFrame(rows)
        if not df.empty:
            df.to_csv(path, index=False)

    if "SECID" not in df.columns:
        return []
    secids = [str(value) for value in df["SECID"].dropna().unique()]
    secids.sort()
    return secids


def _board_for_kind(settings: AppSettings, dataset: str) -> Optional[str]:
    return settings.moex.shares_board if dataset == "shares" else settings.moex.futures_board


def _engine_for_kind(settings: AppSettings, dataset: str) -> str:
    return settings.moex.engine_shares if dataset == "shares" else settings.moex.engine_futures


def _market_for_kind(settings: AppSettings, dataset: str) -> str:
    return settings.moex.market_shares if dataset == "shares" else settings.moex.market_futures


def _cap_end_date(start: date, end: date, max_days: int) -> date:
    if max_days <= 0:
        return end
    return min(end, start + timedelta(days=max_days - 1))


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normalize_candles(raw: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(raw)
    if df.empty:
        return df
    if "begin" in df.columns:
        df["date"] = pd.to_datetime(df["begin"]).dt.date
    columns = ["date"] + [col for col in df.columns if col != "date"]
    return df[columns]


def _append_candles(path: Path, df: pd.DataFrame) -> None:
    if df.empty:
        return
    header = not path.exists()
    df.to_csv(path, mode="a", header=header, index=False)


def _read_last_date(path: Path) -> Optional[date]:
    if not path.exists():
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                return None
            pos = handle.tell() - 1
            while pos > 0:
                handle.seek(pos)
                if handle.read(1) == b"\n":
                    break
                pos -= 1
            line = handle.readline().decode("utf-8", errors="ignore").strip()
        if not line or line.lower().startswith("date,"):
            return None
        value = line.split(",", 1)[0]
        return date.fromisoformat(value)
    except (OSError, ValueError):
        return None


def _get_candles_with_retry(
    client: MoexIssClient,
    engine: str,
    market: str,
    board: Optional[str],
    secid: str,
    from_date: date,
    till_date: date,
    retries: int,
    retry_backoff_sec: float,
) -> list[dict]:
    attempt = 0
    while True:
        try:
            return client.get_candles(engine, market, secid, board, from_date, till_date, interval=24)
        except requests.exceptions.RequestException:
            attempt += 1
            if attempt > max(retries, 0):
                raise
            time.sleep(retry_backoff_sec * attempt)
