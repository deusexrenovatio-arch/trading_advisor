from datetime import date, datetime

import pytest

from moex_carry.backtest_v2 import (
    BacktestPrecomputed,
    ScoreParams,
    batch_score,
    build_feature_matrices,
)
from moex_carry.domain.models import KeyRate
from moex_carry.domain.portfolio import PairSpec, SnapshotPerPair, SnapshotPerPairEvents, SnapshotPerPairLq


def test_batch_score_penalties():
    day = date(2025, 1, 1)
    pair = PairSpec(stock_secid="AAA", future_secid="AAA_F")
    snapshot = SnapshotPerPair(
        as_of=datetime.combine(day, datetime.min.time()),
        stock_secid="AAA",
        future_secid="AAA_F",
        floor_rate_annual=0.05,
        floor_pass=True,
        rtc_pct=0.001,
        spread_pct=0.02,
        dte=10,
        lq=SnapshotPerPairLq(spread_bps_stock=2.0, spread_bps_fut=3.0, liquidity_pass=True),
        events=SnapshotPerPairEvents(warnings=["event_blocked"]),
    )

    precomputed = BacktestPrecomputed(
        trading_days=[day],
        snapshots_by_day={day: [snapshot]},
        stock_bars_by_day={day: []},
        fut_bars_by_day={day: []},
        dividends=[],
        key_rates=[KeyRate(date=day, rate=0.1)],
        events={},
        resolved_config={"rates": {"r_cb_annual": 0.1}},
        warnings=[],
    )

    features = build_feature_matrices(precomputed, [pair])
    params = ScoreParams(
        w_floor=1.0,
        w_alpha=0.0,
        w_liq=1.0,
        w_event=1.0,
        k_event=0.2,
        tp_pct=0.01,
        sl_pct=0.01,
        max_spread_bps_stock=1.0,
        max_spread_bps_fut=2.0,
    )

    scores = batch_score(features, [params])[0]
    assert scores.shape == (1, 1)
    assert scores[0, 0] == pytest.approx(-2.25)
