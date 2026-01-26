from __future__ import annotations

from datetime import date, datetime, timedelta

from moex_carry.domain.portfolio import (
    PairSpec,
    PortfolioState,
    PositionState,
    SnapshotPerPair,
    SnapshotPerPairAlpha,
    SnapshotPerPairLq,
    SnapshotPerPairScores,
)
from moex_carry.portfolio.allocation import AllocationInput, compute_allocation_weights
from moex_carry.portfolio.contracts import RebalanceConfig
from moex_carry.portfolio.rebalance_controller import (
    EXIT_EXPIRY,
    EXIT_LIQ,
    EXIT_SL,
    EXIT_TIME,
    EXIT_TP,
    PortfolioRebalanceController,
    ROTATION_REPLACE,
    pair_key,
)


def _pair(stock: str, fut: str, expiry: date | None = None, multiplier: float = 1.0) -> PairSpec:
    return PairSpec(stock_secid=stock, future_secid=fut, expiry=expiry, multiplier=multiplier)


def _snapshot(
    *,
    stock: str,
    fut: str,
    as_of: datetime,
    dte: int = 10,
    spot_mid: float = 100.0,
    fut_mid: float = 100.0,
    floor_pass: bool = True,
    liq_pass: bool = True,
    total_score: float = 0.5,
    score_floor: float = 0.1,
    score_alpha: float = 0.1,
    sigma: float = 1.0,
    spread_exit: float = 0.0,
    rtc_pct: float = 0.0,
) -> SnapshotPerPair:
    expiry = as_of.date() + timedelta(days=dte)
    return SnapshotPerPair(
        as_of=as_of,
        stock_secid=stock,
        future_secid=fut,
        expiry=expiry,
        spot_mid=spot_mid,
        future_mid=fut_mid,
        dte=dte,
        spread_exit_exec_pct=spread_exit,
        rtc_pct=rtc_pct,
        floor_pass=floor_pass,
        lq=SnapshotPerPairLq(liquidity_pass=liq_pass),
        scores=SnapshotPerPairScores(
            total_score=total_score,
            score_floor=score_floor,
            score_alpha=score_alpha,
        ),
        alpha=SnapshotPerPairAlpha(sigma_h=sigma),
    )


def _position(
    pair: PairSpec,
    *,
    as_of: datetime,
    quantity: int = 10,
    entry_spread: float = 0.0,
    entry_days_ago: int = 1,
    liq_streak: int = 0,
) -> PositionState:
    return PositionState(
        pair=pair,
        direction="cash_and_carry",
        quantity_stock=float(quantity),
        quantity_fut=float(-quantity),
        entry_date=as_of.date() - timedelta(days=entry_days_ago),
        entry_spread_exec_pct=entry_spread,
        liq_fail_streak=liq_streak,
    )


def _run_single(position: PositionState, snapshot: SnapshotPerPair, config: RebalanceConfig):
    portfolio = PortfolioState(as_of=snapshot.as_of, cash=100_000.0, equity=100_000.0, positions=[position])
    controller = PortfolioRebalanceController()
    return controller.rebalance([snapshot], portfolio, config)


def test_hard_exit_tp():
    as_of = datetime(2026, 1, 10)
    pair = _pair("AAA", "AAA_F", expiry=as_of.date() + timedelta(days=20))
    snapshot = _snapshot(stock="AAA", fut="AAA_F", as_of=as_of, spread_exit=0.02)
    position = _position(pair, as_of=as_of, entry_spread=0.0)
    config = RebalanceConfig(
        soft_rebalance_frequency="NONE",
        hard_checks_frequency="DAILY",
        TP_pct=0.01,
        SL_pct=0.05,
        close_buffer_days=2,
    )
    result = _run_single(position, snapshot, config)
    key = pair_key("AAA", "AAA_F")
    assert EXIT_TP in result.reasons[key]
    sides = {(order.instrument, order.side) for order in result.orders}
    assert ("AAA", "sell") in sides
    assert ("AAA_F", "buy") in sides


def test_hard_exit_sl():
    as_of = datetime(2026, 1, 10)
    pair = _pair("BBB", "BBB_F", expiry=as_of.date() + timedelta(days=20))
    snapshot = _snapshot(stock="BBB", fut="BBB_F", as_of=as_of, spread_exit=-0.02)
    position = _position(pair, as_of=as_of, entry_spread=0.0)
    config = RebalanceConfig(
        soft_rebalance_frequency="NONE",
        hard_checks_frequency="DAILY",
        TP_pct=0.05,
        SL_pct=0.01,
    )
    result = _run_single(position, snapshot, config)
    key = pair_key("BBB", "BBB_F")
    assert EXIT_SL in result.reasons[key]


def test_hard_exit_expiry():
    as_of = datetime(2026, 1, 10)
    pair = _pair("CCC", "CCC_F", expiry=as_of.date() + timedelta(days=1))
    snapshot = _snapshot(stock="CCC", fut="CCC_F", as_of=as_of, dte=1)
    position = _position(pair, as_of=as_of, entry_spread=0.0)
    config = RebalanceConfig(
        soft_rebalance_frequency="NONE",
        hard_checks_frequency="DAILY",
        close_buffer_days=2,
    )
    result = _run_single(position, snapshot, config)
    key = pair_key("CCC", "CCC_F")
    assert EXIT_EXPIRY in result.reasons[key]


def test_hard_exit_time():
    as_of = datetime(2026, 1, 10)
    pair = _pair("DDD", "DDD_F", expiry=as_of.date() + timedelta(days=20))
    snapshot = _snapshot(stock="DDD", fut="DDD_F", as_of=as_of)
    position = _position(pair, as_of=as_of, entry_spread=0.0, entry_days_ago=5)
    config = RebalanceConfig(
        soft_rebalance_frequency="NONE",
        hard_checks_frequency="DAILY",
        h_max_days=5,
    )
    result = _run_single(position, snapshot, config)
    key = pair_key("DDD", "DDD_F")
    assert EXIT_TIME in result.reasons[key]


def test_hard_exit_liquidity_streak():
    as_of = datetime(2026, 1, 10)
    pair = _pair("EEE", "EEE_F", expiry=as_of.date() + timedelta(days=20))
    snapshot = _snapshot(stock="EEE", fut="EEE_F", as_of=as_of, liq_pass=False)
    position = _position(pair, as_of=as_of, entry_spread=0.0, liq_streak=1)
    config = RebalanceConfig(
        soft_rebalance_frequency="NONE",
        hard_checks_frequency="DAILY",
        liquidity_exit_streak=2,
    )
    result = _run_single(position, snapshot, config)
    key = pair_key("EEE", "EEE_F")
    assert EXIT_LIQ in result.reasons[key]


def test_hysteresis_enter_vs_keep():
    as_of = datetime(2026, 1, 10)
    pair_a = _pair("AAA", "AAA_F", expiry=as_of.date() + timedelta(days=20))
    pair_b = _pair("BBB", "BBB_F", expiry=as_of.date() + timedelta(days=20))
    snap_a = _snapshot(stock="AAA", fut="AAA_F", as_of=as_of, total_score=0.5)
    snap_b = _snapshot(stock="BBB", fut="BBB_F", as_of=as_of, total_score=0.5)
    position = _position(pair_a, as_of=as_of, entry_spread=0.0)
    portfolio = PortfolioState(as_of=as_of, cash=100_000.0, equity=100_000.0, positions=[position])
    config = RebalanceConfig(
        soft_rebalance_frequency="DAILY",
        hard_checks_frequency="NONE",
        score_threshold_mode="ABSOLUTE",
        enter_total_score_min=0.6,
        keep_total_score_min=0.4,
        max_pairs_held=2,
    )
    controller = PortfolioRebalanceController()
    result = controller.rebalance([snap_a, snap_b], portfolio, config)
    target_ids = {pair_key(tp.pair.stock_secid, tp.pair.future_secid) for tp in result.target_positions}
    assert pair_key("AAA", "AAA_F") in target_ids
    assert pair_key("BBB", "BBB_F") not in target_ids


def test_rotation_replacement_threshold():
    as_of = datetime(2026, 1, 10)
    pair_a = _pair("AAA", "AAA_F", expiry=as_of.date() + timedelta(days=20))
    pair_b = _pair("BBB", "BBB_F", expiry=as_of.date() + timedelta(days=20))
    snap_a = _snapshot(stock="AAA", fut="AAA_F", as_of=as_of, total_score=0.2)
    snap_b = _snapshot(stock="BBB", fut="BBB_F", as_of=as_of, total_score=0.4)
    position = _position(pair_a, as_of=as_of, entry_spread=0.0)
    portfolio = PortfolioState(as_of=as_of, cash=100_000.0, equity=100_000.0, positions=[position])
    config = RebalanceConfig(
        soft_rebalance_frequency="DAILY",
        hard_checks_frequency="NONE",
        score_threshold_mode="ABSOLUTE",
        enter_total_score_min=0.0,
        keep_total_score_min=-1.0,
        max_pairs_held=1,
        replacement_threshold_score_gap_pct=0.5,
    )
    controller = PortfolioRebalanceController()
    result = controller.rebalance([snap_a, snap_b], portfolio, config)
    target_ids = {pair_key(tp.pair.stock_secid, tp.pair.future_secid) for tp in result.target_positions}
    assert pair_key("BBB", "BBB_F") in target_ids
    assert pair_key("AAA", "AAA_F") in result.reasons
    assert ROTATION_REPLACE in result.reasons[pair_key("AAA", "AAA_F")]


def test_band_rebalance_skips_small_change():
    as_of = datetime(2026, 1, 10)
    pair = _pair("AAA", "AAA_F", expiry=as_of.date() + timedelta(days=20))
    snap = _snapshot(stock="AAA", fut="AAA_F", as_of=as_of, total_score=1.0)
    position = _position(pair, as_of=as_of, entry_spread=0.0, quantity=10)
    portfolio = PortfolioState(as_of=as_of, cash=1100.0, equity=1100.0, positions=[position])
    config = RebalanceConfig(
        soft_rebalance_frequency="DAILY",
        hard_checks_frequency="NONE",
        max_pairs_held=1,
        target_utilization=1.0,
        allocation_method="EQUAL",
        rebalance_band=0.2,
    )
    controller = PortfolioRebalanceController()
    result = controller.rebalance([snap], portfolio, config)
    assert not result.orders


def test_turnover_cap_scales_entries_but_not_hard_exits():
    as_of = datetime(2026, 1, 10)
    pair_a = _pair("AAA", "AAA_F", expiry=as_of.date() + timedelta(days=1))
    pair_b = _pair("BBB", "BBB_F", expiry=as_of.date() + timedelta(days=20))
    snap_a = _snapshot(stock="AAA", fut="AAA_F", as_of=as_of, dte=0)
    snap_b = _snapshot(stock="BBB", fut="BBB_F", as_of=as_of, total_score=1.0)
    pos_a = _position(pair_a, as_of=as_of, quantity=5)
    portfolio = PortfolioState(as_of=as_of, cash=100_000.0, equity=100_000.0, positions=[pos_a])
    config = RebalanceConfig(
        soft_rebalance_frequency="DAILY",
        hard_checks_frequency="DAILY",
        max_pairs_held=2,
        turnover_limit_pct=0.0,
    )
    controller = PortfolioRebalanceController()
    result = controller.rebalance([snap_a, snap_b], portfolio, config)
    instruments = {order.instrument for order in result.orders}
    assert "AAA" in instruments
    assert "AAA_F" in instruments
    assert "BBB" not in instruments


def test_score_risk_parity_weights_sigma_penalty():
    inputs = [
        AllocationInput(pair_id="A", score=1.0, sigma=1.0, score_floor=0.0, score_alpha=0.0),
        AllocationInput(pair_id="B", score=1.0, sigma=2.0, score_floor=0.0, score_alpha=0.0),
    ]
    weights = compute_allocation_weights(inputs, "SCORE_RISK_PARITY", max_weight=None, alpha_overlay_weight=1.0, epsilon=1e-9)
    assert weights["A"] > weights["B"]
