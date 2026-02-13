from datetime import date, timedelta

import pandas as pd
import pytest

import moex_carry.pipeline as pipeline
from moex_carry.config import (
    AppSettings,
    DataConfig,
    SpreadCarryAlphaConfig,
    StrategyConfig,
)


class _FakeMinuteOnlyClient:
    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[tuple[str, date, date, int]] = []

    def get_candles(
        self,
        engine: str,
        market: str,
        secid: str,
        board: str,
        from_date: date,
        till_date: date,
        interval: int = 24,
    ):
        if interval != 1:
            raise AssertionError(f"expected interval=1 for executable mode, got {interval}")
        self.calls.append((secid, from_date, till_date, interval))
        rows = []
        day = from_date
        while day <= till_date:
            day_text = day.isoformat()
            if secid == "AAA":
                rows.extend(
                    [
                        {"begin": f"{day_text} 10:00:00", "close": 100.0, "volume": 10},
                        {"begin": f"{day_text} 10:01:00", "close": 101.0, "volume": 20},
                    ]
                )
            else:
                rows.extend(
                    [
                        {"begin": f"{day_text} 10:01:00", "close": 1000.0, "volume": 5},
                        {"begin": f"{day_text} 10:02:00", "close": 1005.0, "volume": 6},
                    ]
                )
            day += timedelta(days=1)
        return rows

    def get_marketdata(self, engine: str, market: str, board: str, secid: str):
        return [{"LAST": 100.0 if secid == "AAA" else 1000.0}]


def _prepare_fixture(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    expiry = date.today() + timedelta(days=30)
    pd.DataFrame(
        [
            {
                "SECID": "AAA",
                "SHORTNAME": "Alpha",
                "BOARDID": "TQBR",
                "CURRENCYID": "RUB",
            }
        ]
    ).to_csv(raw_dir / "shares.csv", index=False)
    pd.DataFrame(
        [
            {
                "SECID": "AAH6",
                "ASSETCODE": "AAA",
                "LASTTRADEDATE": expiry.isoformat(),
                "LOTVOLUME": 10,
                "MULTIPLIER": 1,
                "MINSTEP": 1,
            }
        ]
    ).to_csv(raw_dir / "futures.csv", index=False)
    pd.DataFrame([{"date": date.today().isoformat(), "rate": 0.1}]).to_csv(
        raw_dir / "key_rates.csv", index=False
    )


def test_fetch_pair_common_minute_daily_uses_shared_timestamp():
    settings = AppSettings(
        spread_carry_alpha=SpreadCarryAlphaConfig(
            price_source="common_minute_close",
            common_minute_anchor="last",
        )
    )
    client = _FakeMinuteOnlyClient()
    day = date(2026, 2, 9)

    df = pipeline._fetch_pair_common_minute_daily(
        client,
        settings=settings,
        stock_secid="AAA",
        future_secid="AAH6",
        from_date=day,
        till_date=day,
        future_scale=10.0,
        anchor="last",
    )

    assert not df.empty
    row = df.iloc[0]
    assert row["date"] == day
    assert row["spot"] == pytest.approx(101.0)
    assert row["future"] == pytest.approx(100.0)
    assert row["spot_volume"] == pytest.approx(30.0)
    assert row["future_volume"] == pytest.approx(11.0)
    assert pd.to_datetime(row["exec_ts"]).strftime("%H:%M:%S") == "10:01:00"


def test_compute_pairs_uses_common_minute_mode(tmp_path, monkeypatch):
    _prepare_fixture(tmp_path)
    monkeypatch.setattr(pipeline, "MoexIssClient", _FakeMinuteOnlyClient)
    monkeypatch.setattr(pipeline, "_load_dividends", lambda *_args, **_kwargs: [])

    settings = AppSettings(
        data=DataConfig(data_dir=str(tmp_path), compute_lookback_days=2),
        strategy=StrategyConfig(intraday_marketdata=False),
        spread_carry_alpha=SpreadCarryAlphaConfig(
            price_source="common_minute_close",
            common_minute_anchor="last",
        ),
    )

    result = pipeline.compute_pairs(settings, return_df=True, max_pairs=1, save_csv=False)
    assert result is not None
    assert not result.empty
    row = result.iloc[0]
    assert row["stock"] == "AAA"
    assert row["future"] == "AAH6"
    assert row["spot"] == pytest.approx(101.0)
    assert row["future_price"] == pytest.approx(100.0)


def test_fetch_pair_common_minute_daily_batches_range_requests():
    settings = AppSettings(
        spread_carry_alpha=SpreadCarryAlphaConfig(
            price_source="common_minute_close",
            common_minute_anchor="last",
        )
    )
    client = _FakeMinuteOnlyClient()
    start = date(2026, 2, 9)
    end = date(2026, 2, 11)

    df = pipeline._fetch_pair_common_minute_daily(
        client,
        settings=settings,
        stock_secid="AAA",
        future_secid="AAH6",
        from_date=start,
        till_date=end,
        future_scale=10.0,
        anchor="last",
    )

    assert len(df) == 3
    # One range request per leg, not day-by-day.
    assert len(client.calls) == 2
