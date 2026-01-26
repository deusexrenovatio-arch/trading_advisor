from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional


@dataclass
class PairSpec:
    stock_secid: str
    future_secid: str
    expiry: Optional[date] = None
    lot_size: Optional[float] = None
    multiplier: Optional[float] = None
    tick_size: Optional[float] = None
    currency: str = "RUB"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DailyInstrumentBar:
    secid: str
    date: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    last: Optional[float] = None
    volume: Optional[float] = None
    open_interest: Optional[float] = None
    vwap: Optional[float] = None


@dataclass
class SnapshotPerPairLq:
    spread_bps_stock: Optional[float] = None
    spread_bps_fut: Optional[float] = None
    dollar_vol_stock: Optional[float] = None
    dollar_vol_fut: Optional[float] = None
    avg_dollar_vol: Optional[float] = None
    days_to_exit: Optional[float] = None
    open_interest: Optional[float] = None
    liquidity_pass: Optional[bool] = None


@dataclass
class SnapshotPerPairAlpha:
    zscore: Optional[float] = None
    sigma_h: Optional[float] = None
    p_hit_tp: Optional[float] = None
    p_hit_sl: Optional[float] = None
    half_life: Optional[float] = None
    tp_net: Optional[float] = None
    sl_net: Optional[float] = None


@dataclass
class SnapshotPerPairScores:
    score_floor: Optional[float] = None
    score_alpha: Optional[float] = None
    total_score: Optional[float] = None
    penalty_liq: Optional[float] = None
    penalty_event: Optional[float] = None


@dataclass
class SnapshotPerPairEvents:
    news_severity: Optional[str] = None
    dividend_ex_dates: list[date] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SnapshotPerPair:
    as_of: datetime
    stock_secid: str
    future_secid: str
    expiry: Optional[date] = None
    spot_bid: Optional[float] = None
    spot_ask: Optional[float] = None
    spot_mid: Optional[float] = None
    spot_open: Optional[float] = None
    spot_close: Optional[float] = None
    future_bid: Optional[float] = None
    future_ask: Optional[float] = None
    future_mid: Optional[float] = None
    future_open: Optional[float] = None
    future_close: Optional[float] = None
    dte: Optional[int] = None
    tau: Optional[float] = None
    pv_div: Optional[float] = None
    div_sum: Optional[float] = None
    spread_mid: Optional[float] = None
    spread_pct: Optional[float] = None
    spread_entry_exec: Optional[float] = None
    spread_exit_exec: Optional[float] = None
    spread_entry_exec_pct: Optional[float] = None
    spread_exit_exec_pct: Optional[float] = None
    rtc_pct: Optional[float] = None
    floor_rate_annual: Optional[float] = None
    floor_pass: Optional[bool] = None
    decision: Optional[str] = None
    snapshot_id: Optional[str] = None
    snapshot_hash: Optional[str] = None
    snapshot_as_of: Optional[datetime] = None
    lq: SnapshotPerPairLq = field(default_factory=SnapshotPerPairLq)
    alpha: SnapshotPerPairAlpha = field(default_factory=SnapshotPerPairAlpha)
    scores: SnapshotPerPairScores = field(default_factory=SnapshotPerPairScores)
    events: SnapshotPerPairEvents = field(default_factory=SnapshotPerPairEvents)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionState:
    pair: PairSpec
    direction: str
    quantity_stock: float
    quantity_fut: float
    entry_date: Optional[date] = None
    entry_price_stock: Optional[float] = None
    entry_price_fut: Optional[float] = None
    mark_price_stock: Optional[float] = None
    mark_price_fut: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    realized_pnl: Optional[float] = None
    state: str = "open"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Order:
    order_id: str
    instrument: str
    side: str
    order_type: str
    quantity: float
    price: Optional[float] = None
    status: str = "new"
    created_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Fill:
    fill_id: str
    order_id: str
    instrument: str
    side: str
    quantity: float
    price: float
    fee: Optional[float] = None
    filled_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PortfolioState:
    as_of: datetime
    cash: float
    equity: Optional[float] = None
    margin_used: Optional[float] = None
    positions: list[PositionState] = field(default_factory=list)
    open_orders: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
