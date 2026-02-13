from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

PRELOAD_SCHEMA_VERSION = 1


@dataclass
class MinuteSeriesPayload:
    series_base: pd.DataFrame
    dividends: list[Any]
    source: str


def load_pair_minute_series(
    *,
    data_dir: Path,
    stock: str,
    future: str,
    start_date: date,
    end_date: date,
) -> MinuteSeriesPayload | None:
    payload = _load_from_preload_cache(
        data_dir=data_dir,
        stock=stock,
        future=future,
        start_date=start_date,
        end_date=end_date,
    )
    if payload is not None:
        return payload
    return _load_from_intraday_series_csv(
        data_dir=data_dir,
        stock=stock,
        future=future,
        start_date=start_date,
        end_date=end_date,
    )


def _filter_range(frame: pd.DataFrame, start_date: date, end_date: date) -> pd.DataFrame:
    if frame.empty:
        return frame
    work = frame.copy()
    if "date" in work.columns:
        work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.date
    elif "exec_ts" in work.columns:
        work["date"] = pd.to_datetime(work["exec_ts"], errors="coerce").dt.date
    work = work.dropna(subset=["date"])
    work = work[(work["date"] >= start_date) & (work["date"] <= end_date)]
    return work.reset_index(drop=True)


def _load_from_preload_cache(
    *,
    data_dir: Path,
    stock: str,
    future: str,
    start_date: date,
    end_date: date,
) -> MinuteSeriesPayload | None:
    cache_dir = Path(data_dir) / "output" / "intraday_preload_cache"
    if not cache_dir.exists():
        return None
    pattern = f"{stock}_{future}_*.pkl"
    candidates = sorted(cache_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            payload = pd.read_pickle(path)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if int(payload.get("schema_version", -1)) != PRELOAD_SCHEMA_VERSION:
            continue
        series = payload.get("series_base")
        if not isinstance(series, pd.DataFrame) or series.empty:
            continue
        filtered = _filter_range(series, start_date, end_date)
        if filtered.empty:
            continue
        dividends = payload.get("dividends")
        if not isinstance(dividends, list):
            dividends = []
        return MinuteSeriesPayload(
            series_base=filtered,
            dividends=dividends,
            source=str(path).replace("\\", "/"),
        )
    return None


def _load_from_intraday_series_csv(
    *,
    data_dir: Path,
    stock: str,
    future: str,
    start_date: date,
    end_date: date,
) -> MinuteSeriesPayload | None:
    path = Path(data_dir) / "output" / "intraday_minute_series" / f"intraday_minute_series_{stock}_{future}.csv"
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path)
    except Exception:
        return None
    if frame.empty:
        return None
    filtered = _filter_range(frame, start_date, end_date)
    if filtered.empty:
        return None
    return MinuteSeriesPayload(
        series_base=filtered,
        dividends=[],
        source=str(path).replace("\\", "/"),
    )
