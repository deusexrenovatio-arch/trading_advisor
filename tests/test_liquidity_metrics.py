from moex_carry.analytics.liquidity import days_to_exit, dollar_volume, evaluate_liquidity, spread_bps


def test_spread_bps():
    assert spread_bps(99.0, 101.0, 100.0) == 200.0


def test_dollar_volume():
    assert dollar_volume(100.0, 10.0, multiplier=2.0) == 2000.0


def test_days_to_exit():
    value = days_to_exit(position_notional=100000.0, avg_dollar_vol=50000.0, participation_rate=0.1)
    assert value == 20.0


def test_evaluate_liquidity():
    ok = evaluate_liquidity(
        spread_bps_stock_value=50.0,
        spread_bps_fut_value=40.0,
        dollar_vol_stock_value=1_000_000.0,
        dollar_vol_fut_value=2_000_000.0,
        open_interest=10_000.0,
        days_to_exit_value=5.0,
        max_spread_bps_stock=100.0,
        max_spread_bps_fut=80.0,
        min_dollar_vol_stock=100_000.0,
        min_dollar_vol_fut=100_000.0,
        min_open_interest=1_000.0,
        max_days_to_exit=10.0,
    )
    assert ok is True
