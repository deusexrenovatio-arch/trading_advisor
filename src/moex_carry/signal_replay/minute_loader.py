from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
import threading
from typing import Any

import pandas as pd

PRELOAD_SCHEMA_VERSION = 1
_PRELOAD_PAYLOAD_CACHE_MAX = 128
_SERIES_FRAME_CACHE_MAX = 128
_PRELOAD_CANDIDATES_CACHE_MAX = 128

_PRELOAD_PAYLOAD_CACHE_LOCK = threading.Lock()
_PRELOAD_PAYLOAD_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

_SERIES_FRAME_CACHE_LOCK = threading.Lock()
_SERIES_FRAME_CACHE: "OrderedDict[str, pd.DataFrame]" = OrderedDict()

_PRELOAD_CANDIDATES_CACHE_LOCK = threading.Lock()
_PRELOAD_CANDIDATES_CACHE: "OrderedDict[str, list[str]]" = OrderedDict()


@dataclass
class MinuteSeriesPayload:
    series_base: pd.DataFrame
    dividends: list[Any]
    source: str


def _normalize_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def _safe_mtime(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except OSError:
        return 0


def _cache_get(cache: OrderedDict[str, Any], lock: threading.Lock, key: str) -> Any | None:
    with lock:
        value = cache.get(key)
        if value is None:
            return None
        cache.move_to_end(key)
        return value


def _cache_set(
    cache: OrderedDict[str, Any],
    lock: threading.Lock,
    key: str,
    value: Any,
    max_size: int,
) -> Any:
    with lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > max_size:
            cache.popitem(last=False)
    return value


def _candidate_paths(cache_dir: Path, pattern: str) -> list[Path]:
    dir_key = _normalize_path(cache_dir)
    mtime = _safe_mtime(cache_dir)
    key = f"{dir_key}|{pattern}|{mtime}"
    cached = _cache_get(_PRELOAD_CANDIDATES_CACHE, _PRELOAD_CANDIDATES_CACHE_LOCK, key)
    if cached is not None:
        return [Path(path) for path in cached]
    paths = sorted(cache_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    serialized = [_normalize_path(path) for path in paths]
    _cache_set(
        _PRELOAD_CANDIDATES_CACHE,
        _PRELOAD_CANDIDATES_CACHE_LOCK,
        key,
        serialized,
        _PRELOAD_CANDIDATES_CACHE_MAX,
    )
    return [Path(path) for path in serialized]


def _read_preload_payload(path: Path) -> dict[str, Any] | None:
    path_key = _normalize_path(path)
    mtime = _safe_mtime(path)
    key = f"{path_key}|{mtime}"
    cached = _cache_get(_PRELOAD_PAYLOAD_CACHE, _PRELOAD_PAYLOAD_CACHE_LOCK, key)
    if cached is not None:
        return cached
    try:
        payload = pd.read_pickle(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return _cache_set(
        _PRELOAD_PAYLOAD_CACHE,
        _PRELOAD_PAYLOAD_CACHE_LOCK,
        key,
        payload,
        _PRELOAD_PAYLOAD_CACHE_MAX,
    )


def _read_intraday_series(path: Path) -> pd.DataFrame | None:
    path_key = _normalize_path(path)
    mtime = _safe_mtime(path)
    key = f"{path_key}|{mtime}"
    cached = _cache_get(_SERIES_FRAME_CACHE, _SERIES_FRAME_CACHE_LOCK, key)
    if cached is not None:
        return cached
    try:
        frame = pd.read_csv(path)
    except Exception:
        return None
    if frame.empty:
        return None
    return _cache_set(
        _SERIES_FRAME_CACHE,
        _SERIES_FRAME_CACHE_LOCK,
        key,
        frame,
        _SERIES_FRAME_CACHE_MAX,
    )


def load_pair_minute_series(
    *,
    data_dir: Path,
    stock: str,
    future: str,
    start_date: date,
    end_date: date,
) -> MinuteSeriesPayload | None:
    preload_payload = _load_from_preload_cache(
        data_dir=data_dir,
        stock=stock,
        future=future,
        start_date=start_date,
        end_date=end_date,
    )
    csv_payload = _load_from_intraday_series_csv(
        data_dir=data_dir,
        stock=stock,
        future=future,
        start_date=start_date,
        end_date=end_date,
    )
    candidates = [payload for payload in (preload_payload, csv_payload) if payload is not None]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    return max(candidates, key=_payload_priority_key)


def _payload_priority_key(payload: MinuteSeriesPayload) -> tuple[datetime, int, int]:
    watermark = _payload_watermark(payload.series_base)
    source_priority = 1 if "intraday_minute_series" in payload.source else 0
    return (
        watermark or datetime.fromtimestamp(0, tz=timezone.utc),
        int(len(payload.series_base)),
        source_priority,
    )


def _payload_watermark(frame: pd.DataFrame) -> datetime | None:
    if frame.empty:
        return None
    for column in ("exec_ts", "timestamp", "date"):
        if column not in frame.columns:
            continue
        parsed = pd.to_datetime(frame[column], errors="coerce", utc=True)
        parsed = parsed.dropna()
        if parsed.empty:
            continue
        return parsed.max().to_pydatetime()
    return None


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
    candidates = _candidate_paths(cache_dir, pattern)
    for path in candidates:
        payload = _read_preload_payload(path)
        if payload is None:
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
    frame = _read_intraday_series(path)
    if frame is None:
        return None
    filtered = _filter_range(frame, start_date, end_date)
    if filtered.empty:
        return None
    return MinuteSeriesPayload(
        series_base=filtered,
        dividends=[],
        source=str(path).replace("\\", "/"),
    )
