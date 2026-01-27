import json
from datetime import date, timedelta

from moex_carry.domain.models import DividendEvent, KeyRate
from moex_carry.domain.portfolio import DailyInstrumentBar, PairSpec
from moex_carry.forward import (
    ALERT_MISSING_QUOTES,
    ALERT_SPREAD_TOO_WIDE,
    ForwardEngineConfig,
    ForwardTestEngine,
    JsonStateStore,
    MarketSnapshotInput,
)
from moex_carry.forward.interfaces import IMarketDataAdapter
from moex_carry.portfolio.contracts import RebalanceConfig


class DummyMarketData(IMarketDataAdapter):
    def __init__(self, eod_map, open_map):
        self._eod_map = eod_map
        self._open_map = open_map

    def get_eod_snapshot(self, trading_day: date) -> MarketSnapshotInput:
        return self._eod_map[trading_day]

    def get_open_snapshot(self, trading_day: date) -> MarketSnapshotInput:
        return self._open_map[trading_day]

    def get_trading_day(self, as_of=None) -> date:
        return (as_of.date() if as_of else date.today())

    def get_next_trading_day(self, trading_day: date) -> date:
        return trading_day + timedelta(days=1)

    def is_market_closed(self, as_of=None) -> bool:
        return False


def _make_bar(secid: str, trading_day: date, price: float, bid: float | None = None, ask: float | None = None):
    bid = bid if bid is not None else price * 0.999
    ask = ask if ask is not None else price * 1.001
    mid = (bid + ask) / 2.0
    return DailyInstrumentBar(
        secid=secid,
        date=trading_day,
        open=price,
        close=price,
        bid=bid,
        ask=ask,
        mid=mid,
        volume=100,
    )


def _resolved_config() -> dict:
    return {
        "execution": {"price_mode": "BIDASK"},
        "rates": {"day_count": "ACT/365", "use_trading_days": False},
        "costs": {},
        "liquidity": {},
        "strategy": {},
        "portfolio": {"account_equity": 1_000.0},
        "universe": {"max_pairs": 1},
    }


def _rebalance_config() -> RebalanceConfig:
    return RebalanceConfig(
        soft_rebalance_frequency="DAILY",
        hard_checks_frequency="DAILY",
        max_pairs_held=1,
        max_contracts_per_pair=1,
        min_contracts_per_pair=1,
    )


def test_forward_engine_persists_state(tmp_path):
    trading_day = date(2026, 1, 23)
    pair = PairSpec(stock_secid="AAA", future_secid="AAH6", multiplier=1.0, expiry=trading_day + timedelta(days=30))
    snapshot = MarketSnapshotInput(
        as_of=trading_day,
        pairs=[pair],
        stock_bars=[_make_bar("AAA", trading_day, 100.0)],
        fut_bars=[_make_bar("AAH6", trading_day, 101.0)],
        dividends=[DividendEvent(secid="AAA", ex_date=trading_day, amount=0.0, currency="RUB", status="")],
        key_rates=[KeyRate(date=trading_day, rate=0.0)],
    )
    market = DummyMarketData({trading_day: snapshot}, {trading_day: snapshot})

    store = JsonStateStore(tmp_path / "state")
    engine = ForwardTestEngine(
        market_data=market,
        state_store=store,
        resolved_config=_resolved_config(),
        rebalance_config=_rebalance_config(),
        engine_config=ForwardEngineConfig(initial_cash=1_000.0),
    )

    orders = engine.run_eod(trading_day)
    assert orders

    engine_restart = ForwardTestEngine(
        market_data=market,
        state_store=store,
        resolved_config=_resolved_config(),
        rebalance_config=_rebalance_config(),
        engine_config=ForwardEngineConfig(initial_cash=1_000.0),
    )
    engine_restart.run_after_close(trading_day)
    assert engine_restart.state is not None
    assert len(engine_restart.state.portfolio.open_orders) == len(orders)


def test_forward_engine_daily_cycle(tmp_path):
    day1 = date(2026, 1, 23)
    day2 = date(2026, 1, 24)
    pair = PairSpec(stock_secid="AAA", future_secid="AAH6", multiplier=1.0, expiry=day1 + timedelta(days=30))

    eod_day1 = MarketSnapshotInput(
        as_of=day1,
        pairs=[pair],
        stock_bars=[_make_bar("AAA", day1, 100.0)],
        fut_bars=[_make_bar("AAH6", day1, 101.0)],
        dividends=[],
        key_rates=[],
    )
    open_day2 = MarketSnapshotInput(
        as_of=day2,
        pairs=[pair],
        stock_bars=[_make_bar("AAA", day2, 102.0)],
        fut_bars=[_make_bar("AAH6", day2, 103.0)],
        dividends=[],
        key_rates=[],
    )
    eod_day2 = MarketSnapshotInput(
        as_of=day2,
        pairs=[pair],
        stock_bars=[_make_bar("AAA", day2, 103.0)],
        fut_bars=[_make_bar("AAH6", day2, 104.0)],
        dividends=[],
        key_rates=[],
    )

    market = DummyMarketData({day1: eod_day1, day2: eod_day2}, {day2: open_day2})
    store = JsonStateStore(tmp_path / "state")
    engine = ForwardTestEngine(
        market_data=market,
        state_store=store,
        resolved_config=_resolved_config(),
        rebalance_config=_rebalance_config(),
        engine_config=ForwardEngineConfig(initial_cash=1_000.0),
    )

    orders_day1 = engine.run_eod(day1)
    assert orders_day1

    fills = engine.run_open(day2)
    assert fills
    assert engine.state is not None
    assert engine.state.portfolio.positions

    engine.run_eod(day2)
    assert engine.state.last_eod_day == day2

    trades = store.trades_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(trades) == len(fills)


def test_forward_engine_alerts_for_missing_quotes_and_spread(tmp_path):
    trading_day = date(2026, 1, 25)
    pair_missing = PairSpec(stock_secid="AAA", future_secid="AAH6", multiplier=1.0, expiry=trading_day + timedelta(days=30))
    pair_wide = PairSpec(stock_secid="BBB", future_secid="BBH6", multiplier=1.0, expiry=trading_day + timedelta(days=30))

    snapshot = MarketSnapshotInput(
        as_of=trading_day,
        pairs=[pair_missing, pair_wide],
        stock_bars=[_make_bar("BBB", trading_day, 100.0, bid=95.0, ask=105.0)],
        fut_bars=[_make_bar("AAH6", trading_day, 101.0), _make_bar("BBH6", trading_day, 102.0)],
        dividends=[],
        key_rates=[],
    )

    market = DummyMarketData({trading_day: snapshot}, {trading_day: snapshot})
    store = JsonStateStore(tmp_path / "state")
    engine = ForwardTestEngine(
        market_data=market,
        state_store=store,
        resolved_config=_resolved_config(),
        rebalance_config=_rebalance_config(),
        engine_config=ForwardEngineConfig(initial_cash=1_000.0, max_spread_bps_stock=50.0),
    )

    engine.run_eod(trading_day)

    alert_lines = store.alerts_path.read_text(encoding="utf-8").strip().splitlines()
    codes = {json.loads(line)["code"] for line in alert_lines if line.strip()}
    assert ALERT_MISSING_QUOTES in codes
    assert ALERT_SPREAD_TOO_WIDE in codes
