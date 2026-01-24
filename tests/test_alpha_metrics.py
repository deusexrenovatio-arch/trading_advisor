from moex_carry.analytics.alpha import alpha_metrics, hit_probabilities, round_trip_cost


def test_round_trip_cost():
    value = round_trip_cost(stock_buy=101.0, stock_sell=99.0, fut_buy=102.0, fut_sell=100.0, fees_rt=0.5)
    assert value == 4.5


def test_hit_probabilities():
    spread_pct = [0.0, 0.01, 0.02, 0.01, 0.03]
    p_tp, p_sl = hit_probabilities(spread_pct, horizon=2, tp=0.01, sl=0.01)
    assert p_tp == 1.0
    assert p_sl == 1.0 / 3.0


def test_alpha_metrics_quantiles():
    spread_pct = [0.0, 0.01, 0.02, 0.01, 0.03]
    metrics = alpha_metrics(spread_pct, horizon=2, tp=0.01, sl=0.01)
    assert metrics.mfe_q90 >= metrics.mfe_q50
    assert metrics.mae_q50 <= 0.0
