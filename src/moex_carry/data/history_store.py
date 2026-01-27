from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from moex_carry.domain.models import DividendEvent, KeyRate
from moex_carry.domain.portfolio import DailyInstrumentBar, PairSpec


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    if not path.exists():
        return []
    df = pd.read_csv(path)
    if df.empty:
        return []
    df = _normalize_columns(df)
    df = _ensure_date_column(df)
    if "date" not in df.columns:
        return []
    df = df.dropna(subset=["date"])
    if start_date is not None:
        df = df[df["date"] >= start_date]
    if end_date is not None:
        df = df[df["date"] <= end_date]
    if df.empty:
        return []
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
    return bars


def _load_key_rates(data_dir: Path) -> list[KeyRate]:
    path = Path(data_dir) / "raw" / "key_rates.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    if df.empty or "date" not in df.columns or "rate" not in df.columns:
        return []
    rates: list[KeyRate] = []
    for row in df.to_dict("records"):
        day = pd.to_datetime(row.get("date"), errors="coerce").date()
        rate = _to_float(row.get("rate"))
        if day and rate is not None:
            rates.append(KeyRate(date=day, rate=float(rate)))
    return rates


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
        for secid in secids:
            path = base / f"{secid}.csv"
            bars = _load_candles(
                path,
                secid,
                start_date=self.start_date,
                end_date=self.end_date,
            )
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
