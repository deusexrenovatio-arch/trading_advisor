import numpy as np
import pytest

from moex_carry.analytics.alpha import alpha_matrices_fast, alpha_metrics


def test_alpha_matrices_fast_matches_series():
    spread = np.array([[0.1], [0.2], [0.15], [0.25]], dtype=float)
    horizon = 2
    tp = 0.05
    sl = 0.05
    p_hit_tp, p_hit_sl, sigma_h, half_life = alpha_matrices_fast(
        spread,
        horizon=horizon,
        tp=tp,
        sl=sl,
        history_days=90,
    )

    series: list[float] = []
    for idx in range(spread.shape[0]):
        series.append(float(spread[idx, 0]))
        expected = alpha_metrics(series, horizon=horizon, tp=tp, sl=sl)
        assert p_hit_tp[idx, 0] == pytest.approx(expected.p_hit_tp)
        assert p_hit_sl[idx, 0] == pytest.approx(expected.p_hit_sl)
        assert sigma_h[idx, 0] == pytest.approx(expected.sigma_h)
        assert half_life[idx, 0] == pytest.approx(expected.half_life)
