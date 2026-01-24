from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional


@dataclass
class Instrument:
    secid: str
    name: str
    instrument_type: str
    currency: str = "RUB"
    board: Optional[str] = None


@dataclass
class ContractSpec:
    secid: str
    asset_code: str
    expiry: date
    lot_size: float
    price_step: float
    multiplier: float


@dataclass
class PairMapping:
    stock_secid: str
    future_secid: str
    expiry: date


@dataclass
class Quote:
    secid: str
    timestamp: datetime
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    volume: Optional[float]


@dataclass
class DividendEvent:
    secid: str
    ex_date: date
    amount: float
    currency: str
    status: str


@dataclass
class KeyRate:
    date: date
    rate: float


@dataclass
class Signal:
    timestamp: datetime
    stock_secid: str
    future_secid: str
    direction: str
    score: float
    reasons: list[str]
    metrics: dict[str, Any]


@dataclass
class Trade:
    entry_date: date
    exit_date: Optional[date]
    stock_secid: str
    future_secid: str
    direction: str
    entry_price: float
    exit_price: Optional[float]
    pnl: Optional[float]


@dataclass
class BacktestRun:
    run_id: str
    started_at: datetime
    params: dict[str, Any]


@dataclass
class StockMarketPoint:
    timestamp: datetime
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    last: Optional[float]
    volume: Optional[float]
    dollar_volume: Optional[float]


@dataclass
class FutMarketPoint:
    timestamp: datetime
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    last: Optional[float]
    volume: Optional[float]
    open_interest: Optional[float]
