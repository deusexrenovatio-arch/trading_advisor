from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Optional

from moex_carry.domain.models import DividendEvent, KeyRate
from moex_carry.domain.portfolio import DailyInstrumentBar, PairSpec, PortfolioState


@dataclass
class MarketSnapshotInput:
    as_of: date
    pairs: list[PairSpec]
    stock_bars: Mapping[str, DailyInstrumentBar] | Iterable[DailyInstrumentBar] | None
    fut_bars: Mapping[str, DailyInstrumentBar] | Iterable[DailyInstrumentBar] | None
    dividends: Iterable[DividendEvent] | None = None
    key_rates: Iterable[KeyRate] | None = None
    events: Mapping[str, list[date]] | None = None
    timestamp: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ForwardAlert:
    code: str
    as_of: datetime
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EquityPoint:
    as_of: datetime
    equity: float
    cash: float
    drawdown_pct: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ForwardState:
    config_hash: str
    portfolio: PortfolioState
    last_eod_day: Optional[date] = None
    last_open_day: Optional[date] = None
    last_after_close_day: Optional[date] = None
    metadata: dict[str, Any] = field(default_factory=dict)
