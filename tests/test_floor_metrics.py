import pytest

from moex_carry.analytics.floor import compute_floor_metrics


def test_floor_metrics_full_cash():
    metrics = compute_floor_metrics(
        spot_buy=100.0,
        fut_sell=105.0,
        div_sum=1.0,
        fees_rt=0.5,
        r_cb_annual=0.1,
        r_fund_annual=0.1,
        tau=0.5,
        dte=180,
        floor_tolerance=0.0,
        riskbuffer_floor=0.0,
        capital_base_mode="FULL_CASH",
    )
    assert metrics.capital_base == 100.0
    assert metrics.floor_rate_annual < 0.1
    assert metrics.floor_pass is False


def test_floor_metrics_margin_aware():
    metrics = compute_floor_metrics(
        spot_buy=100.0,
        fut_sell=105.0,
        div_sum=2.0,
        fees_rt=1.0,
        r_cb_annual=0.1,
        r_fund_annual=0.1,
        tau=0.5,
        dte=100,
        floor_tolerance=0.0,
        riskbuffer_floor=0.0,
        capital_base_mode="MARGIN_AWARE",
        margin_stock_pct=0.2,
        margin_fut_pct=0.1,
        var_margin_buffer_pct=0.05,
    )
    assert metrics.capital_base == 35.5
    assert metrics.floor_rate_annual == pytest.approx((1.0 / 35.5) * 3.65)
