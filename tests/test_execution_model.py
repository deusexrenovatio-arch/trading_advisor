import pytest

from moex_carry.execution.model import build_execution_prices


def test_execution_prices_bps():
    prices = build_execution_prices(
        stock_bid=99.0,
        stock_ask=101.0,
        fut_bid=100.0,
        fut_ask=102.0,
        slip_stock_bps=10.0,
        slip_fut_bps=20.0,
    )
    assert prices.stock_buy > 101.0
    assert prices.stock_sell < 99.0
    assert prices.fut_sell < 100.0
    assert prices.fut_buy > 102.0


def test_execution_prices_ticks():
    prices = build_execution_prices(
        stock_bid=100.0,
        stock_ask=100.0,
        fut_bid=200.0,
        fut_ask=200.0,
        slip_fut_bps=100.0,
        slip_fut_ticks=2,
        tick_size_fut=0.25,
    )
    assert prices.fut_sell == 199.5
    assert prices.fut_buy == 200.5


def test_execution_prices_mid_fallback():
    prices = build_execution_prices(
        stock_bid=None,
        stock_ask=None,
        fut_bid=None,
        fut_ask=None,
        stock_mid=100.0,
        fut_mid=200.0,
    )
    assert prices.stock_buy == 100.0
    assert prices.stock_sell == 100.0
    assert prices.fut_sell == 200.0
    assert prices.fut_buy == 200.0


def test_execution_prices_ohlc_synthetic():
    prices = build_execution_prices(
        stock_bid=None,
        stock_ask=None,
        fut_bid=None,
        fut_ask=None,
        stock_open=100.0,
        stock_close=110.0,
        fut_open=200.0,
        fut_close=190.0,
        mode="OHLC",
        half_spread_bps=50.0,
    )
    assert prices.stock_buy == pytest.approx(100.5)
    assert prices.stock_sell == pytest.approx(109.45)
    assert prices.fut_sell == pytest.approx(199.0)
    assert prices.fut_buy == pytest.approx(190.95)
