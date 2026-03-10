from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from moex_carry.signal_engine.core.types import Candle, TF
from moex_carry.signal_engine.data.candles import InMemoryCandleProvider, IssCandleProvider, IssInstrumentRoute


class _FakeIssClient:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls: list[dict[str, object]] = []

    def get_candles(self, engine, market, security, board, date_from, date_to, *, interval):
        self.calls.append(
            {
                "engine": engine,
                "market": market,
                "security": security,
                "board": board,
                "date_from": date_from,
                "date_to": date_to,
                "interval": interval,
            }
        )
        return list(self.rows)


@pytest.mark.parametrize(
    ("tf", "expected_interval"),
    [
        (TF.D1, 24),
        (TF.H1, 60),
        (TF.M5, 5),
    ],
)
def test_iss_candle_provider_maps_tf_to_interval(tf, expected_interval):
    client = _FakeIssClient(
        [
            {
                "begin": "2026-03-01T10:00:00+03:00",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 10.0,
            }
        ]
    )
    provider = IssCandleProvider(
        client,
        route=IssInstrumentRoute(engine="futures", market="forts", board="RFUD"),
        timezone="Europe/Moscow",
    )
    end_ts = datetime(2026, 3, 1, 23, 0, tzinfo=ZoneInfo("Europe/Moscow"))

    candles = provider.get_candles("BRK6", tf=tf, end_ts=end_ts, limit=1)

    assert len(candles) == 1
    assert client.calls[-1]["interval"] == expected_interval
    assert client.calls[-1]["engine"] == "futures"
    assert client.calls[-1]["market"] == "forts"
    assert client.calls[-1]["board"] == "RFUD"


def test_iss_candle_provider_filters_sorts_and_limits():
    client = _FakeIssClient(
        [
            {
                "begin": "2026-03-01T10:10:00+03:00",
                "open": 102.0,
                "high": 103.0,
                "low": 101.5,
                "close": 102.5,
                "volume": 13.0,
            },
            {
                "begin": "2026-03-01T10:00:00+03:00",
                "open": 100.0,
                "high": 101.0,
                "low": 99.5,
                "close": 100.5,
                "value": 210.5,
            },
            {
                "begin": "2026-03-01T10:05:00+03:00",
                "open": 101.0,
                "high": 102.0,
                "low": 100.5,
                "close": 101.5,
                "volume": 12.0,
            },
            {
                "begin": "2026-03-01T10:15:00+03:00",
                "open": 103.0,
                "high": 104.0,
                "low": 102.5,
                "close": 103.5,
                "volume": 14.0,
            },
        ]
    )
    provider = IssCandleProvider(
        client,
        route=IssInstrumentRoute(engine="futures", market="forts", board="RFUD"),
        timezone="Europe/Moscow",
    )
    end_ts = datetime(2026, 3, 1, 10, 10, tzinfo=ZoneInfo("Europe/Moscow"))

    candles = provider.get_candles("BRK6", tf=TF.M5, end_ts=end_ts, limit=3)
    assert [item.ts.strftime("%H:%M") for item in candles] == ["10:00", "10:05", "10:10"]
    assert candles[0].volume == 210.5
    assert candles[1].volume == 12.0
    assert candles[2].volume == 13.0
    assert candles[0].ts.tzinfo is not None

    limited = provider.get_candles("BRK6", tf=TF.M5, end_ts=end_ts, limit=2)
    assert [item.ts.strftime("%H:%M") for item in limited] == ["10:05", "10:10"]


def test_inmemory_candle_provider_returns_last_slice_without_resort():
    tz = ZoneInfo("Europe/Moscow")
    payload = {
        ("BRK6", TF.M5): [
            Candle(ts=datetime(2026, 3, 1, 10, 10, tzinfo=tz), open=10.3, high=10.5, low=10.2, close=10.4, volume=13.0),
            Candle(ts=datetime(2026, 3, 1, 10, 0, tzinfo=tz), open=10.0, high=10.2, low=9.9, close=10.1, volume=11.0),
            Candle(ts=datetime(2026, 3, 1, 10, 5, tzinfo=tz), open=10.1, high=10.3, low=10.0, close=10.2, volume=12.0),
            Candle(ts=datetime(2026, 3, 1, 10, 15, tzinfo=tz), open=10.4, high=10.6, low=10.3, close=10.5, volume=14.0),
        ]
    }
    provider = InMemoryCandleProvider(payload)
    end_ts = datetime(2026, 3, 1, 10, 10, tzinfo=tz)
    candles = provider.get_candles("BRK6", tf=TF.M5, end_ts=end_ts, limit=2)
    assert [item.ts.strftime("%H:%M") for item in candles] == ["10:05", "10:10"]
