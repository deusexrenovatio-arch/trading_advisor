from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from moex_carry.signal_engine.core.types import Candle, TF


class DataProvider(Protocol):
    def get_candles(self, instrument_id: str, tf: TF, end_ts: datetime, limit: int) -> list[Candle]:
        """Return candles sorted ascending by ts, timezone-aware."""


@dataclass(frozen=True)
class IssInstrumentRoute:
    engine: str
    market: str
    board: str | None


class IssCandleProvider:
    def __init__(
        self,
        client,
        *,
        route: IssInstrumentRoute,
        timezone: str = "Europe/Moscow",
    ) -> None:
        self.client = client
        self.route = route
        self.tz = ZoneInfo(str(timezone))

    def get_candles(self, instrument_id: str, tf: TF, end_ts: datetime, limit: int) -> list[Candle]:
        end_local = end_ts.astimezone(self.tz) if end_ts.tzinfo is not None else end_ts.replace(tzinfo=self.tz)
        period = max(int(limit), 1)
        interval = _iss_interval(tf)
        bars_per_day = _bars_per_day(tf)
        lookback_days = max(int(math.ceil(period / max(bars_per_day, 1))), 1) + 5
        start_local = end_local - timedelta(days=lookback_days)
        rows = self.client.get_candles(
            self.route.engine,
            self.route.market,
            instrument_id,
            self.route.board,
            start_local.date(),
            end_local.date(),
            interval=interval,
        )
        output: list[Candle] = []
        for row in rows:
            begin = row.get("begin")
            if begin is None:
                continue
            ts = datetime.fromisoformat(str(begin).replace("Z", "+00:00"))
            local_ts = ts.astimezone(self.tz) if ts.tzinfo is not None else ts.replace(tzinfo=self.tz)
            if local_ts > end_local:
                continue
            output.append(
                Candle(
                    ts=local_ts,
                    open=float(row.get("open", 0.0)),
                    high=float(row.get("high", 0.0)),
                    low=float(row.get("low", 0.0)),
                    close=float(row.get("close", 0.0)),
                    volume=float(row.get("value", row.get("volume", 0.0)) or 0.0),
                )
            )
        output.sort(key=lambda item: item.ts)
        if len(output) > period:
            output = output[-period:]
        return output


class InMemoryCandleProvider:
    def __init__(self, payload: dict[tuple[str, TF], list[Candle]]) -> None:
        self.payload = payload
        self._series: dict[tuple[str, TF], list[Candle]] = {}
        self._timestamps: dict[tuple[str, TF], list[datetime]] = {}
        for key, rows in payload.items():
            ordered = _sorted_if_needed(rows)
            self._series[key] = ordered
            self._timestamps[key] = [item.ts for item in ordered]

    def get_candles(self, instrument_id: str, tf: TF, end_ts: datetime, limit: int) -> list[Candle]:
        key = (instrument_id, tf)
        rows = self._series.get(key, [])
        if not rows:
            return []
        timestamps = self._timestamps.get(key, [])
        end_idx = bisect.bisect_right(timestamps, end_ts)
        if end_idx <= 0:
            return []
        take = max(int(limit), 0)
        if take <= 0:
            take = end_idx
        start_idx = max(end_idx - take, 0)
        return rows[start_idx:end_idx]


def _iss_interval(tf: TF) -> int:
    if tf == TF.D1:
        return 24
    if tf == TF.H1:
        return 60
    if tf == TF.M5:
        return 5
    raise ValueError(f"unsupported_tf:{tf}")


def _bars_per_day(tf: TF) -> int:
    if tf == TF.D1:
        return 1
    if tf == TF.H1:
        return 24
    if tf == TF.M5:
        return 24 * 12
    return 1


def _sorted_if_needed(rows: list[Candle]) -> list[Candle]:
    if len(rows) <= 1:
        return list(rows)
    for idx in range(1, len(rows)):
        if rows[idx - 1].ts > rows[idx].ts:
            return sorted(rows, key=lambda item: item.ts)
    return list(rows)
