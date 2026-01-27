from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, Sequence

from moex_carry.domain.portfolio import Fill, Order, PortfolioState, SnapshotPerPair
from moex_carry.forward.models import EquityPoint, ForwardAlert, ForwardState, MarketSnapshotInput


class IMarketDataAdapter(Protocol):
    def get_eod_snapshot(self, trading_day: date) -> MarketSnapshotInput:
        ...

    def get_open_snapshot(self, trading_day: date) -> MarketSnapshotInput:
        ...

    def get_trading_day(self, as_of: datetime | None = None) -> date:
        ...

    def get_next_trading_day(self, trading_day: date) -> date:
        ...

    def is_market_closed(self, as_of: datetime | None = None) -> bool:
        ...


class IPaperBroker(Protocol):
    def submit_orders(
        self,
        orders: Sequence[Order],
        portfolio: PortfolioState,
        as_of: datetime,
    ) -> list[Order]:
        ...

    def simulate_fills(
        self,
        orders: Sequence[Order],
        snapshots: Sequence[SnapshotPerPair],
        as_of: datetime,
    ) -> list[Fill]:
        ...

    def apply_fills(
        self,
        fills: Sequence[Fill],
        portfolio: PortfolioState,
        as_of: datetime,
    ) -> list[Fill]:
        ...


class IStateStore(Protocol):
    def load(self) -> ForwardState | None:
        ...

    def save(self, state: ForwardState) -> None:
        ...

    def append_trade(self, fill: Fill) -> None:
        ...

    def append_equity(self, point: EquityPoint) -> None:
        ...

    def append_alert(self, alert: ForwardAlert) -> None:
        ...


class IReporter(Protocol):
    def daily_report(
        self,
        trading_day: date,
        portfolio: PortfolioState,
        equity: EquityPoint,
        snapshots: Sequence[SnapshotPerPair],
        alerts: Sequence[ForwardAlert],
    ) -> None:
        ...
