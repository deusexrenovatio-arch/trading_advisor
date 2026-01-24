from datetime import date

import pandas as pd

from moex_carry.pipeline import compute_spread_series


def test_compute_spread_series_basic():
    prices = pd.DataFrame(
        {
            "date": [date(2024, 1, 1), date(2024, 1, 2)],
            "spot": [100.0, 101.0],
            "future_price": [102.0, 103.0],
        }
    )
    series = compute_spread_series(prices, date(2024, 12, 31), dividends=[], key_rates=[])
    assert len(series) == 2
    assert "spread_mid" in series.columns
    assert "spread_pct" in series.columns
