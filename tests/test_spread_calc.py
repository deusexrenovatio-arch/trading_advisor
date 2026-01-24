from moex_carry.analytics.spread import spread_entry_exec, spread_exit_exec, spread_mid, spread_pct


def test_spread_mid_basic():
    value = spread_mid(spot_mid=100.0, pv_div=2.0, fut_mid=99.0)
    assert value == -1.0


def test_spread_execs():
    entry = spread_entry_exec(spot_buy=101.0, pv_div=1.0, fut_sell=100.0)
    exit_value = spread_exit_exec(spot_sell=99.0, pv_div=1.0, fut_buy=98.0)
    assert entry == 0.0
    assert exit_value == 0.0


def test_spread_pct():
    assert spread_pct(-1.0, 100.0) == -0.01
