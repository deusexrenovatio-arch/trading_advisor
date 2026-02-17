from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path
import threading
from typing import Any, Iterable

import pandas as pd

from moex_carry.domain.models import DividendEvent, KeyRate
from moex_carry.domain.portfolio import DailyInstrumentBar, PairSpec
from moex_carry.perf import resolve_pair_workers

_CANDLE_BARS_CACHE_MAX = 512
_KEY_RATE_CACHE_MAX = 8
_CANDLE_BARS_CACHE_LOCK = threading.Lock()
_CANDLE_BARS_CACHE: "OrderedDict[str, list[DailyInstrumentBar]]" = OrderedDict()
_KEY_RATE_CACHE_LOCK = threading.Lock()
_KEY_RATE_CACHE: "OrderedDict[str, list[KeyRate]]" = OrderedDict()


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(col).strip().lower() for col in df.columns]
    return df


def _ensure_date_column(df: pd.DataFrame) -> pd.DataFrame:
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        return df
    if "begin" in df.columns:
        df["date"] = pd.to_datetime(df["begin"], errors="coerce").dt.date
        return df
    if "end" in df.columns:
        df["date"] = pd.to_datetime(df["end"], errors="coerce").dt.date
        return df
    return df


def _load_candles(
    path: Path,
    secid: str,
    *,
    start_date: date | None,
    end_date: date | None,
) -> list[DailyInstrumentBar]:
    bars_all = _load_candles_full(path, secid)
    if not bars_all:
        return []
    if start_date is None and end_date is None:
        return list(bars_all)
    bars: list[DailyInstrumentBar] = []
    for bar in bars_all:
        if start_date is not None and bar.date < start_date:
            continue
        if end_date is not None and bar.date > end_date:
            continue
        bars.append(bar)
    return bars


def _load_candles_full(path: Path, secid: str) -> list[DailyInstrumentBar]:
    if not path.exists():
        return []
    key = f"{_normalize_path(path)}|{_safe_mtime(path)}"
    cached = _cache_get(_CANDLE_BARS_CACHE, _CANDLE_BARS_CACHE_LOCK, key)
    if cached is not None:
        return cached
    df = pd.read_csv(path)
    if df.empty:
        return _cache_set(_CANDLE_BARS_CACHE, _CANDLE_BARS_CACHE_LOCK, key, [], _CANDLE_BARS_CACHE_MAX)
    df = _normalize_columns(df)
    df = _ensure_date_column(df)
    if "date" not in df.columns:
        return _cache_set(_CANDLE_BARS_CACHE, _CANDLE_BARS_CACHE_LOCK, key, [], _CANDLE_BARS_CACHE_MAX)
    df = df.dropna(subset=["date"])
    if df.empty:
        return _cache_set(_CANDLE_BARS_CACHE, _CANDLE_BARS_CACHE_LOCK, key, [], _CANDLE_BARS_CACHE_MAX)
    bars: list[DailyInstrumentBar] = []
    for row in df.to_dict("records"):
        day = row.get("date")
        if not isinstance(day, date):
            continue
        open_price = _to_float(row.get("open"))
        high = _to_float(row.get("high"))
        low = _to_float(row.get("low"))
        close = _to_float(row.get("close"))
        volume = _to_float(row.get("volume"))
        value = _to_float(row.get("value"))
        open_interest = _to_float(row.get("openinterest") or row.get("openposition"))
        vwap = None
        if value is not None and volume:
            vwap = value / volume if volume else None
        mid = close if close is not None else open_price
        last = close if close is not None else open_price
        bars.append(
            DailyInstrumentBar(
                secid=secid,
                date=day,
                open=open_price,
                high=high,
                low=low,
                close=close,
                bid=None,
                ask=None,
                mid=mid,
                last=last,
                volume=volume,
                open_interest=open_interest,
                vwap=vwap,
            )
        )
    return _cache_set(_CANDLE_BARS_CACHE, _CANDLE_BARS_CACHE_LOCK, key, bars, _CANDLE_BARS_CACHE_MAX)


def _load_key_rates(data_dir: Path) -> list[KeyRate]:
    path = Path(data_dir) / "raw" / "key_rates.csv"
    if not path.exists():
        return []
    key = f"{_normalize_path(path)}|{_safe_mtime(path)}"
    cached = _cache_get(_KEY_RATE_CACHE, _KEY_RATE_CACHE_LOCK, key)
    if cached is not None:
        return list(cached)
    df = pd.read_csv(path)
    if df.empty or "date" not in df.columns or "rate" not in df.columns:
        return []
    rates: list[KeyRate] = []
    for row in df.to_dict("records"):
        day = pd.to_datetime(row.get("date"), errors="coerce").date()
        rate = _to_float(row.get("rate"))
        if day and rate is not None:
            rates.append(KeyRate(date=day, rate=float(rate)))
    cached_rates = _cache_set(_KEY_RATE_CACHE, _KEY_RATE_CACHE_LOCK, key, rates, _KEY_RATE_CACHE_MAX)
    return list(cached_rates)


def _filter_bars(bars: Iterable[DailyInstrumentBar], secids: Iterable[str]) -> list[DailyInstrumentBar]:
    target = set(secids)
    return [bar for bar in bars if bar.secid in target]


class HistoryDataStore:
    def __init__(
        self,
        data_dir: Path,
        pairs: Iterable[PairSpec],
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        dividends: Iterable[DividendEvent] | None = None,
        events: dict[str, list[date]] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.pairs = list(pairs)
        self.stock_secids = sorted({pair.stock_secid for pair in self.pairs})
        self.fut_secids = sorted({pair.future_secid for pair in self.pairs})
        self.start_date = start_date
        self.end_date = end_date
        self._pair_workers = resolve_pair_workers(None)
        self._stock_bars_by_day = self._load_bars("shares", self.stock_secids)
        self._fut_bars_by_day = self._load_bars("futures", self.fut_secids)
        self._calendar = sorted(set(self._stock_bars_by_day) | set(self._fut_bars_by_day))
        self._key_rates = _load_key_rates(self.data_dir)
        self._dividends = list(dividends) if dividends is not None else []
        self._events = dict(events) if events is not None else {}

    def _load_bars(
        self,
        dataset: str,
        secids: Iterable[str],
    ) -> dict[date, list[DailyInstrumentBar]]:
        base = self.data_dir / "history" / "candles" / dataset
        bars_by_day: dict[date, list[DailyInstrumentBar]] = {}
        secid_list = list(secids)
        if not secid_list:
            return bars_by_day

        def _load_for_secid(secid: str) -> tuple[str, list[DailyInstrumentBar]]:
            path = base / f"{secid}.csv"
            bars = _load_candles(
                path,
                secid,
                start_date=self.start_date,
                end_date=self.end_date,
            )
            return secid, bars

        workers = min(self._pair_workers, len(secid_list))
        if workers <= 1:
            loaded_rows = [_load_for_secid(secid) for secid in secid_list]
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                loaded_rows = list(pool.map(_load_for_secid, secid_list))

        for _, bars in loaded_rows:
            for bar in bars:
                bars_by_day.setdefault(bar.date, []).append(bar)
        return bars_by_day

    def get_stock_bars(self, as_of: date, secids: Iterable[str]) -> list[DailyInstrumentBar]:
        return _filter_bars(self._stock_bars_by_day.get(as_of, []), secids)

    def get_fut_bars(self, as_of: date, secids: Iterable[str]) -> list[DailyInstrumentBar]:
        return _filter_bars(self._fut_bars_by_day.get(as_of, []), secids)

    def get_dividends(self) -> list[DividendEvent]:
        return list(self._dividends)

    def get_key_rates(self) -> list[KeyRate]:
        return list(self._key_rates)

    def get_events(self) -> dict[str, list[date]]:
        return dict(self._events)

    def get_calendar(self, start_date: date, end_date: date) -> list[date]:
        if not self._calendar:
            return []
        return [day for day in self._calendar if start_date <= day <= end_date]

    def bars_for_open(self, bars: Iterable[DailyInstrumentBar]) -> list[DailyInstrumentBar]:
        adjusted: list[DailyInstrumentBar] = []
        for bar in bars:
            open_price = bar.open if bar.open is not None else bar.close
            if open_price is None:
                adjusted.append(bar)
                continue
            adjusted.append(
                replace(
                    bar,
                    close=open_price,
                    mid=open_price,
                    last=open_price,
                    bid=None,
                    ask=None,
                )
            )
        return adjusted
