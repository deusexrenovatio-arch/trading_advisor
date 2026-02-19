from datetime import date
from types import SimpleNamespace

import pytest

from moex_carry.pipeline import _build_signal_trade_plan


def test_build_signal_trade_plan_cash_and_carry():
    alpha_cfg = SimpleNamespace(H_max_days=10, entry_price_tolerance_pct=0.002)
    alpha_stats = SimpleNamespace(p_hit_tp=0.6, p_hit_sl=0.25, half_life=4.4)

    plan = _build_signal_trade_plan(
        direction="cash_and_carry",
        as_of_snapshot=date(2026, 2, 9),
        spot_mid=100.0,
        future_mid=98.0,
        pv_div=1.0,
        spread_mid_value=1.0,
        spread_pct_value=0.01,
        tp_net=0.02,
        sl_net=0.015,
        alpha_stats=alpha_stats,
        alpha_cfg=alpha_cfg,
    )

    assert plan["entry_stock_min"] == pytest.approx(99.8)
    assert plan["entry_stock_max"] == pytest.approx(100.2)
    assert plan["entry_spread_pct_min"] == pytest.approx(0.00998)
    assert plan["entry_spread_pct_max"] == pytest.approx(0.01002)
    assert plan["tp_spread_pct_level"] == pytest.approx(0.03)
    assert plan["sl_spread_pct_level"] == pytest.approx(-0.005)
    assert plan["tp_stock_level_if_fut_const"] == pytest.approx(102.0)
    assert plan["sl_future_level_if_stock_const"] == pytest.approx(99.5)
    assert plan["forecast_tp_probability"] == pytest.approx(0.6)
    assert plan["forecast_sl_probability"] == pytest.approx(0.25)
    assert plan["forecast_exit_days"] == 4
    assert plan["forecast_exit_date"] == "2026-02-13"
    assert plan["forecast_model"] == "half_life_capped"


def test_build_signal_trade_plan_reverse_direction_levels():
    alpha_cfg = SimpleNamespace(H_max_days=8, entry_price_tolerance_pct=0.0015)
    alpha_stats = SimpleNamespace(p_hit_tp=0.45, p_hit_sl=0.35, half_life=0.0)

    plan = _build_signal_trade_plan(
        direction="reverse",
        as_of_snapshot=date(2026, 2, 9),
        spot_mid=100.0,
        future_mid=98.0,
        pv_div=1.0,
        spread_mid_value=1.0,
        spread_pct_value=0.01,
        tp_net=0.02,
        sl_net=0.015,
        alpha_stats=alpha_stats,
        alpha_cfg=alpha_cfg,
    )

    assert plan["tp_spread_pct_level"] == pytest.approx(-0.01)
    assert plan["sl_spread_pct_level"] == pytest.approx(0.025)
    assert plan["forecast_exit_days"] == 8
    assert plan["forecast_model"] == "h_max_days"
