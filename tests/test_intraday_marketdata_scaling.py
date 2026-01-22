from datetime import date, timedelta

import pandas as pd
import pytest

import moex_carry.pipeline as pipeline
from moex_carry.config import AppSettings, DataConfig


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
