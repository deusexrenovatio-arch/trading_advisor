from datetime import date, timedelta

import pandas as pd
import pytest

import moex_carry.pipeline as pipeline
from moex_carry.config import AppSettings, DataConfig, SpreadCarryAlphaConfig


class _FakeMoexClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_marketdata(self, engine: str, market: str, board: str, secid: str):
        if secid == "AAA":
            return [{"LAST": 101.0}]
        return [{"LAST": 1100.0}]


def _fake_fetch_candles(
    _client,
    _engine: str,
    _market: str,
    _board: str,
    secid: str,
    from_date,
    till_date,
    price_scale: float = 1.0,
):
    dates = [from_date, till_date]
    base = 100.0 if secid == "AAA" else 1000.0
    df = pd.DataFrame({"begin": dates, "close": [base, base], "volume": [10, 12]})
    if price_scale and price_scale != 1.0:
        df["close"] = pd.to_numeric(df["close"], errors="coerce") / price_scale
    df["date"] = pd.to_datetime(df["begin"]).dt.date
    df.rename(columns={"close": secid, "volume": f"{secid}_volume"}, inplace=True)
    return df[["date", secid, f"{secid}_volume"]]


def test_intraday_future_marketdata_scales_to_spot_units(tmp_path, monkeypatch):
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
    pd.DataFrame(
        [{"date": date.today().isoformat(), "rate": 0.1}]
    ).to_csv(raw_dir / "key_rates.csv", index=False)

    monkeypatch.setattr(pipeline, "MoexIssClient", _FakeMoexClient)
    monkeypatch.setattr(pipeline, "_fetch_candles", _fake_fetch_candles)
    monkeypatch.setattr(pipeline, "_load_dividends", lambda *_args, **_kwargs: [])

    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    result = pipeline.compute_pairs(settings, return_df=True, max_pairs=1, save_csv=False)
    assert result is not None
    assert not result.empty
    row = result.iloc[0]
    assert row["spot"] == pytest.approx(101.0)
    assert row["future_price"] == pytest.approx(110.0)


class _FakeMoexClientWithBook:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_marketdata(self, engine: str, market: str, board: str, secid: str):
        if secid == "AAA":
            return [
                {
                    "BID": 101.0,
                    "OFFER": 101.1,
                    "BIDDEPTHT": 50,
                    "OFFERDEPTHT": 60,
                    "SYSTIME": "2026-02-09 10:20:00",
                    "UPDATETIME": "10:19:50",
                }
            ]
        return [
            {
                "BID": 1100.0,
                "OFFER": 1101.0,
                "BIDDEPTHT": 8,
                "OFFERDEPTHT": 9,
                "SYSTIME": "2026-02-09 10:20:00",
                "UPDATETIME": "10:19:55",
            }
        ]


def _prepare_intraday_fixture(tmp_path):
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
    pd.DataFrame(
        [{"date": date.today().isoformat(), "rate": 0.1}]
    ).to_csv(raw_dir / "key_rates.csv", index=False)


def test_intraday_orderbook_gate_blocks_on_fut_depth(tmp_path, monkeypatch):
    _prepare_intraday_fixture(tmp_path)
    monkeypatch.setattr(pipeline, "MoexIssClient", _FakeMoexClientWithBook)
    monkeypatch.setattr(pipeline, "_fetch_candles", _fake_fetch_candles)
    monkeypatch.setattr(pipeline, "_load_dividends", lambda *_args, **_kwargs: [])

    settings = AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        spread_carry_alpha=SpreadCarryAlphaConfig(
            require_live_orderbook_for_entry=True,
            min_orderbook_depth_fut=10.0,
        ),
    )
    result = pipeline.compute_pairs(settings, return_df=True, max_pairs=1, save_csv=False)
    assert result is not None
    assert not result.empty
    row = result.iloc[0]
    assert row["decision"] == "SKIP_ORDERBOOK"
    assert bool(row["orderbook_pass"]) is False
    assert "orderbook_fut_depth" in row["orderbook_reasons"]


def test_intraday_orderbook_gate_passes_with_depth_and_age(tmp_path, monkeypatch):
    _prepare_intraday_fixture(tmp_path)
    monkeypatch.setattr(pipeline, "MoexIssClient", _FakeMoexClientWithBook)
    monkeypatch.setattr(pipeline, "_fetch_candles", _fake_fetch_candles)
    monkeypatch.setattr(pipeline, "_load_dividends", lambda *_args, **_kwargs: [])

    settings = AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        spread_carry_alpha=SpreadCarryAlphaConfig(
            require_live_orderbook_for_entry=True,
            min_orderbook_depth_fut=5.0,
            min_orderbook_depth_stock=10.0,
            max_orderbook_age_sec_fut=30.0,
            max_orderbook_age_sec_stock=30.0,
            max_orderbook_imbalance_ratio_fut=2.0,
            max_orderbook_imbalance_ratio_stock=2.0,
        ),
    )
    result = pipeline.compute_pairs(settings, return_df=True, max_pairs=1, save_csv=False)
    assert result is not None
    assert not result.empty
    row = result.iloc[0]
    assert bool(row["orderbook_pass"]) is True
    assert row["decision"] != "SKIP_ORDERBOOK"
