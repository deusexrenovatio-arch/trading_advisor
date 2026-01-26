from datetime import date

import pytest

from moex_carry.domain.models import DividendEvent, KeyRate
from moex_carry.domain.portfolio import DailyInstrumentBar, PairSpec
from moex_carry.snapshot.builder import build_snapshot_universe


def test_snapshot_builder_basic_metrics():
    as_of = date(2025, 1, 1)
    pair = PairSpec(
        stock_secid="AAA",
        future_secid="AAA_F",
        expiry=date(2025, 2, 1),
        multiplier=10.0,
        tick_size=0.1,
    )
    stock_bar = DailyInstrumentBar(
        secid="AAA",
        date=as_of,
        bid=99.0,
        ask=101.0,
        open=100.0,
        close=100.0,
        volume=1000.0,
    )
    fut_bar = DailyInstrumentBar(
        secid="AAA_F",
        date=as_of,
        bid=100.0,
        ask=102.0,
        open=101.0,
        close=101.0,
        volume=500.0,
        open_interest=10_000.0,
    )
    dividends = [
        DividendEvent(
            secid="AAA",
            ex_date=date(2025, 1, 15),
            amount=1.0,
            currency="RUB",
            status="forecast",
        )
    ]
    key_rates = [KeyRate(date=as_of, rate=0.1)]
    resolved_config = {
        "execution": {
            "price_mode": "BIDASK",
            "half_spread_bps": 0.0,
            "slip_stock_bps": 0.0,
            "slip_fut_bps": 0.0,
        },
        "rates": {
            "day_count": "ACT/365",
            "use_trading_days": False,
            "r_cb_annual": 0.1,
            "r_fund_annual": 0.1,
            "r_disc_annual": 0.1,
        },
        "costs": {
            "fee_stock_bps": 10.0,
            "fee_fut_per_contract": 2.0,
        },
        "strategy": {
            "floor_tolerance": 0.0,
            "riskbuffer_floor": 0.0,
            "capital_base_mode": "FULL_CASH",
        },
        "liquidity": {
            "max_spread_bps_stock": 300.0,
            "max_spread_bps_fut": 300.0,
            "min_avg_dollarvol_stock": 50_000.0,
            "min_avg_dollarvol_fut": 50_000.0,
            "min_open_interest": 5_000.0,
            "participation_rate": 0.1,
            "max_days_to_exit": 15.0,
        },
        "portfolio": {"capital_allocated_per_trade": 100_000.0},
    }

    snapshots = build_snapshot_universe(
        as_of=as_of,
        pairs=[pair],
        stock_bars=[stock_bar],
        fut_bars=[fut_bar],
        dividends=dividends,
        key_rates=key_rates,
        resolved_config=resolved_config,
    )
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert isinstance(snapshot.spot_mid, float)
    assert isinstance(snapshot.future_mid, float)
    assert snapshot.rtc_pct == pytest.approx(0.046)
    assert snapshot.lq.liquidity_pass is True
